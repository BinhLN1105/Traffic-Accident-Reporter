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
        public String inputFilePath; // NEW: Store input video path for browser playback
        public int progress = 0;
        public String aiReport; 
        public Object incidents; // List of incidents from JSON
        public List<String> snapshotPaths; // ADDED
        public Boolean autoReport = true; // NEW: Auto-report flag

        public TaskStatus(String id) {
            this.id = id;
            this.status = Status.PENDING;
            this.message = "Queued...";
            this.snapshotPaths = new ArrayList<>();
        }
    }

    private final Map<String, TaskStatus> tasks = new ConcurrentHashMap<>();

    public String submitTask(String inputPath, String outputPath, String pythonScriptPath, boolean isRealtime, String modelType, String customLabels, Double confidenceThreshold, Boolean autoReport) {
        try {
            Map<String, Object> request = new HashMap<>();
            request.put("inputPath", inputPath);
            request.put("outputPath", outputPath);
            request.put("realtime", isRealtime);
            request.put("modelType", modelType);
            request.put("customLabels", customLabels);
            request.put("confidenceThreshold", confidenceThreshold);
            request.put("autoReport", autoReport); // NEW: Pass autoReport flag

            ResponseEntity<Map> response = restTemplate.postForEntity(PYTHON_SERVER_URL + "/process", request, Map.class);
            
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                String jobId = (String) response.getBody().get("jobId");
                
                TaskStatus status = new TaskStatus(jobId);
                status.autoReport = autoReport; // Store for later
                status.inputFilePath = inputPath; // Store input path for browser playback
                tasks.put(jobId, status);
                
                // Only start monitoring thread for Batch mode
                // Realtime mode uses WebRTC connection, no need to poll Python server
                if (!isRealtime) {
                    executor.submit(() -> monitorTask(jobId, outputPath, autoReport));
                } else {
                    System.out.println("Realtime job " + jobId + " - skipping monitoring thread (managed by WebRTC)");
                }
                
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

    // NEW: Generate AI report on-demand (manual mode)
    public String generateReportOnDemand(String taskId) throws Exception {
        TaskStatus status = tasks.get(taskId);
        if (status == null) {
            throw new Exception("Task not found: " + taskId);
        }
        
        // If already has report, return it
        if (status.aiReport != null && !status.aiReport.isEmpty()) {
            return status.aiReport;
        }
        
        // Generate report from snapshots
        if (status.snapshotPaths != null && !status.snapshotPaths.isEmpty()) {
            List<Path> pathList = new ArrayList<>();
            // Use middle snapshot (best quality)
            String middleSnapshot = status.snapshotPaths.get(status.snapshotPaths.size() / 2);
            
            Path fullPath;
            
            // Check if snapshot is a Python server URL (Realtime mode)
            if (middleSnapshot.startsWith("/data/")) {
                // Download from Python server
                String pythonUrl = PYTHON_SERVER_URL + middleSnapshot;
                System.out.println("Downloading snapshot from Python server: " + pythonUrl);
                
                try {
                    // Download image to temp file
                    byte[] imageBytes = restTemplate.getForObject(pythonUrl, byte[].class);
                    if (imageBytes == null || imageBytes.length == 0) {
                        throw new Exception("Failed to download image from Python server");
                    }
                    
                    // Save to temp file
                    Path tempFile = java.nio.file.Files.createTempFile("snapshot_", ".jpg");
                    java.nio.file.Files.write(tempFile, imageBytes);
                    fullPath = tempFile;
                    System.out.println("Saved temp snapshot: " + fullPath);
                } catch (Exception e) {
                    throw new Exception("Failed to download snapshot from Python: " + e.getMessage());
                }
            } else {
                // Local file path (Batch mode)
                Path dataDir = Paths.get(System.getProperty("user.dir")).getParent().resolve("data");
                fullPath = dataDir.resolve(middleSnapshot);
                if (!fullPath.toFile().exists()) {
                    fullPath = Paths.get(middleSnapshot); // Try as-is (already absolute path)
                }
            }
            
            pathList.add(fullPath);
            
            String aiReport = geminiService.analyzeImage(pathList);
            status.aiReport = aiReport;
            return aiReport;
        }
        
        throw new Exception("No snapshots available for analysis");
    }

    // NEW: Update task snapshots from frontend (for Realtime mode)
    public void updateTaskSnapshots(String taskId, List<String> snapshotUrls) {
        TaskStatus status = tasks.get(taskId);
        if (status != null) {
            // Store snapshot URLs (these are Python server URLs like /data/xxx.jpg)
            status.snapshotPaths = new ArrayList<>(snapshotUrls);
            System.out.println("Updated task " + taskId + " with " + snapshotUrls.size() + " snapshot URLs");
        }
    }


    private void monitorTask(String taskId, String outputPath, Boolean autoReport) {
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
                        // DELAY setting COMPLETED until metadata is ready!
                        localStatus.message = "Finalizing Results...";
                        localStatus.outputFilePath = outputPath;
                        
                        // --- POST-PROCESSING: Read Metadata & Call AI & Save to DB ---
                        try {
                            // Python appends .json to the full output path (e.g. video.webm -> video.webm.json)
                            File metadataFile = new File(outputPath + ".json");
                            if (!metadataFile.exists()) {
                                // Fallback: Try replaced extension if appended not found
                                metadataFile = new File(outputPath.replace(".webm", ".json"));
                            }
                            
                            if (metadataFile.exists()) {
                                ObjectMapper mapper = new ObjectMapper();
                                Map<String, Object> metadata = mapper.readValue(metadataFile, Map.class);
                                
                                localStatus.incidents = metadata.get("incidents");
                                
                                boolean hasAccident = (boolean) metadata.getOrDefault("has_accident", false);
                                List<String> snapshotPaths = (List<String>) metadata.get("snapshot_paths");
                                
                                // Store relative paths for Frontend
                                if (snapshotPaths != null) {
                                     localStatus.snapshotPaths = new ArrayList<>();
                                     for(String p : snapshotPaths) {
                                         localStatus.snapshotPaths.add(new File(p).getName());
                                     }
                                }
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

                                // PREVENT DOUBLE PROCESSING: Check if Python already generated the report
                                String existingAiReport = (String) metadata.get("aiReport");
                                Integer existingIncidentId = (Integer) metadata.get("incidentId");

                                // Only run AI analysis if autoReport is enabled
                                if (autoReport != null && autoReport && hasAccident) {
                                    
                                    if (existingAiReport != null && !existingAiReport.isEmpty()) {
                                        System.out.println("AI Report already generated by Python (Job " + taskId + "). Using existing.");
                                        localStatus.aiReport = existingAiReport;
                                        localStatus.message = "Phân tích hoàn tất (Cached)";
                                        
                                        // If incident already exists in DB (Python created it), we might want to ensure we don't duplicate
                                        // But wait, if Python created it, we usually ignore saving again unless we track the ID.
                                        if (existingIncidentId != null) {
                                             System.out.println("Incident already saved to DB by Python stream (ID: " + existingIncidentId + ")");
                                             // Optionally fetch lookup to ensure data consistency?
                                             // For now, logging is enough. Frontend uses the ID from metadata via TaskStatus potentially?
                                             // Actually TaskStatus doesn't hold INCIDENT ID currently, maybe we should?
                                        } else {
                                             // Report exists but maybe not saved? (Unlikely with curr server.py logic)
                                             // If no ID, maybe we should save? 
                                             // Let's assume if report exists, the incident creation chain worked.
                                        }
                                        
                                    } else {
                                        // Trigger Gemini (Fallback if Python failed to report)
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
                                                    
                                        // SAVE TO DATABASE (Only if fresh report)
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
                                                
                                                // NEW: Set videoUrl
                                                incident.setVideoUrl("/api/videos/download/" + new File(outputPath).getName());
                                                
                                                // NEW: Set snapshotUrls as JSON array
                                                if (snapshotPaths != null && !snapshotPaths.isEmpty()) {
                                                    ObjectMapper snapshotMapper = new ObjectMapper();
                                                    List<String> snapshotUrlList = new ArrayList<>();
                                                    for (String path : snapshotPaths) {
                                                        snapshotUrlList.add("/api/videos/download/" + new File(path).getName());
                                                    }
                                                    incident.setSnapshotUrls(snapshotMapper.writeValueAsString(snapshotUrlList));
                                                }
                                                
                                                // NEW: Set aiReport (full AI analysis)
                                                incident.setAiReport(aiReport);
                                                
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
                            }
                        } catch (Exception e) {
                            System.err.println("Error reading metadata or calling AI: " + e.getMessage());
                            e.printStackTrace();
                        }
                        
                        
                        // FINALLY marks as completed so frontend can fetch full result
                        localStatus.message = "Processing Complete";
                        localStatus.status = Status.COMPLETED;
                        break;
                    } else if ("FAILED".equals(remoteStatus)) {
                        localStatus.status = Status.FAILED;
                        localStatus.message = (String) body.get("message");
                        break;
                    } else if ("STOPPED".equals(remoteStatus) || "READY".equals(remoteStatus)) {
                        // Realtime mode: stream was stopped or is in ready state
                        System.out.println("Realtime job " + taskId + " stopped/ready, ending monitoring.");
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
