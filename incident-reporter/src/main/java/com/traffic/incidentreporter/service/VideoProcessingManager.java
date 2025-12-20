package com.traffic.incidentreporter.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.traffic.incidentreporter.entity.Incident;
import com.traffic.incidentreporter.repository.IncidentRepository;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.http.ResponseEntity;
import java.io.File;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.List;
import java.util.ArrayList;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@Service
public class VideoProcessingManager {

    private final ExecutorService executor = Executors.newFixedThreadPool(3);
    private final RestTemplate restTemplate = new RestTemplate();
    private final GeminiService geminiService; 
    private final IncidentRepository incidentRepository; // Inject Repository
    private final String PYTHON_SERVER_URL = "http://localhost:5000";

    public VideoProcessingManager(GeminiService geminiService, IncidentRepository incidentRepository) {
        this.geminiService = geminiService;
        this.incidentRepository = incidentRepository;
    }

    // Enum for Task Status
    public enum Status {
        PENDING, PROCESSING, COMPLETED, FAILED
    }

    public static class TaskStatus {
        public String id;
        public Status status;
        public String message;
        public String outputFilePath;
        public int progress = 0;
        public String aiReport; 
        public Object incidents; // List of incidents from JSON

        public TaskStatus(String id) {
            this.id = id;
            this.status = Status.PENDING;
            this.message = "Queued...";
        }
    }

    private final Map<String, TaskStatus> tasks = new ConcurrentHashMap<>();

    public String submitTask(String inputPath, String outputPath, String pythonScriptPath) {
        try {
            Map<String, String> request = new HashMap<>();
            request.put("inputPath", inputPath);
            request.put("outputPath", outputPath);

            ResponseEntity<Map> response = restTemplate.postForEntity(PYTHON_SERVER_URL + "/process", request, Map.class);
            
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                String jobId = (String) response.getBody().get("jobId");
                
                TaskStatus status = new TaskStatus(jobId);
                tasks.put(jobId, status);
                
                executor.submit(() -> monitorTask(jobId, outputPath));
                
                return jobId;
            } else {
                throw new RuntimeException("Failed to submit to Python Server");
            }

        } catch (Exception e) {
            e.printStackTrace();
            throw new RuntimeException("Python Server Error: " + e.getMessage());
        }
    }

    public TaskStatus getStatus(String taskId) {
        return tasks.get(taskId);
    }

    private void monitorTask(String taskId, String outputPath) {
        TaskStatus localStatus = tasks.get(taskId);
        
        while (true) {
            try {
                Thread.sleep(1000); 
                
                ResponseEntity<Map> response = restTemplate.getForEntity(PYTHON_SERVER_URL + "/status/" + taskId, Map.class);
                Map body = response.getBody();
                
                if (body != null) {
                    String remoteStatus = (String) body.get("status");
                    int progress = (int) body.get("progress");
                    
                    localStatus.progress = progress;
                    
                    if ("COMPLETED".equals(remoteStatus)) {
                        localStatus.status = Status.COMPLETED;
                        localStatus.message = "Processing Complete";
                        localStatus.outputFilePath = outputPath;
                        
                        // --- POST-PROCESSING: Read Metadata & Call AI & Save to DB ---
                        try {
                            File metadataFile = new File(outputPath.replace(".webm", ".json"));
                            if (!metadataFile.exists()) {
                                // Fallback for legacy .mp4 tasks or if replacement failed
                                metadataFile = new File(outputPath.replace(".mp4", ".json"));
                            }
                            
                            if (metadataFile.exists()) {
                                ObjectMapper mapper = new ObjectMapper();
                                Map<String, Object> metadata = mapper.readValue(metadataFile, Map.class);
                                
                                // READ INCIDENTS LIST
                                localStatus.incidents = metadata.get("incidents");
                                
                                boolean hasAccident = (boolean) metadata.getOrDefault("has_accident", false);
                                List<String> snapshotPaths = (List<String>) metadata.get("snapshot_paths");
                                String legacySnapshot = (String) metadata.get("snapshot_path");
                                
                                // Determine primary snapshot for DB/Display
                                String primarySnapshotPath = legacySnapshot;
                                if (snapshotPaths != null && !snapshotPaths.isEmpty()) {
                                    // Use the "During" shot (index 1) if available, else first
                                    if (snapshotPaths.size() >= 2) {
                                        primarySnapshotPath = snapshotPaths.get(1);
                                    } else {
                                        primarySnapshotPath = snapshotPaths.get(0);
                                    }
                                }

                                if (hasAccident) {
                                    // Trigger Gemini
                                    localStatus.message = "Đang phân tích AI (Đa khung hình)...";
                                    
                                    String aiReport;
                                    if (snapshotPaths != null && !snapshotPaths.isEmpty()) {
                                        // Convert String paths to Path objects
                                        List<Path> fullList = snapshotPaths.stream()
                                                .map(Paths::get)
                                                .toList();
                                        
                                        // Optimization: Limit to 1 Key Frame (Middle/Impact) to maximize success rate
                                        // 3 frames is triggering Overload/Quota too often.
                                        List<Path> pathList = new ArrayList<>();
                                        if (!fullList.isEmpty()) {
                                            pathList.add(fullList.get(fullList.size() / 2)); 
                                        }
                                        
                                        aiReport = geminiService.analyzeImage(pathList);
                                    } else if (legacySnapshot != null) {
                                         // Fallback legacy
                                         aiReport = geminiService.analyzeImage(Paths.get(legacySnapshot));
                                    } else {
                                        aiReport = "Không có hình ảnh để phân tích.";
                                    }

                                    localStatus.aiReport = aiReport;
                                    localStatus.message = "Phân tích hoàn tất";

                                    // SAVE TO DATABASE
                                    try {
                                        if (primarySnapshotPath != null) {
                                            Incident incident = new Incident();
                                            
                                            // MANUAL ID ASSIGNMENT (GAP FILLING STRATEGY)
                                            Long newId = 1L;
                                            if (!incidentRepository.existsById(1L)) {
                                                newId = 1L;
                                            } else {
                                                Long gapId = incidentRepository.findNextAvailableId();
                                                if (gapId != null) {
                                                    newId = gapId;
                                                } else {
                                                    Long maxId = incidentRepository.findMaxId();
                                                    newId = (maxId != null) ? maxId + 1 : 1L;
                                                }
                                            }
                                            incident.setId(newId);

                                            incident.setType("Accident"); 
                                            incident.setTimestamp(LocalDateTime.now());
                                            incident.setDescription(aiReport); 
                                            incident.setLocation("Camera-01 (Video Analysis)");
                                            incident.setImageUrl("/api/videos/download/" + new File(primarySnapshotPath).getName()); 
                                            incident.setAlertSent(false);

                                            incidentRepository.save(incident);
                                            System.out.println("Incident saved to Database: " + incident.getId());
                                        }
                                    } catch (Exception dbEx) {
                                        System.err.println("Database Save Failed: " + dbEx.getMessage());
                                        dbEx.printStackTrace();
                                    }
                                }
                            }
                        } catch (Exception e) {
                            System.err.println("Error reading metadata or calling AI: " + e.getMessage());
                            e.printStackTrace();
                        }
                        
                        break;
                    } else if ("FAILED".equals(remoteStatus)) {
                        localStatus.status = Status.FAILED;
                        localStatus.message = (String) body.get("message");
                        break;
                    } else {
                        localStatus.status = Status.PROCESSING;
                        localStatus.message = "Analyzing... " + progress + "%";
                    }
                }
            } catch (Exception e) {
                // If Python server is unreachable or returns 404, mark as failed
                if (e.getMessage().contains("404")) {
                    localStatus.status = Status.FAILED;
                    localStatus.message = "Task lost on AI Server (Restarted?)";
                    break;
                }
                localStatus.message = "Connection issue... retrying";
            }
        }
    }
}
