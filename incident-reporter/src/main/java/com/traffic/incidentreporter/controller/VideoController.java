package com.traffic.incidentreporter.controller;

import com.traffic.incidentreporter.service.VideoProcessingManager;
import org.springframework.core.io.Resource;
import org.springframework.core.io.UrlResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.net.MalformedURLException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.ArrayList;
import java.util.List;

@RestController
@RequestMapping("/api/videos")
@CrossOrigin(origins = "*")
public class VideoController {

    private final VideoProcessingManager processingManager;
    // Store data in the project root's 'data' folder (Relative path: Up one level -> data)
    private final Path fileStorageLocation = Paths.get("..", "data")
            .toAbsolutePath().normalize();

    public VideoController(VideoProcessingManager processingManager) {
        this.processingManager = processingManager;
        try {
            Files.createDirectories(this.fileStorageLocation);
        } catch (Exception ex) {
            throw new RuntimeException("Could not create the directory where the uploaded files will be stored.", ex);
        }
    }

    @PostMapping("/process")
    public ResponseEntity<Map<String, String>> submitVideo(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "realtime", defaultValue = "false") boolean isRealtime,
            @RequestParam(value = "modelType", defaultValue = "medium") String modelType,
            @RequestParam(value = "customLabels", defaultValue = "accident, vehicle accident") String customLabels,
            @RequestParam(value = "confidenceThreshold", defaultValue = "0.70") Double confidenceThreshold,
            @RequestParam(value = "autoReport", defaultValue = "true") Boolean autoReport) {
        try {
            System.out.println("Received: " + file.getOriginalFilename() + " (Realtime=" + isRealtime + ", Model=" + modelType + ", Labels=" + customLabels + ", Conf=" + confidenceThreshold + ", AutoReport=" + autoReport + ")");
            
            String logFileName = UUID.randomUUID().toString() + "_" + file.getOriginalFilename();
            Path inputLocation = this.fileStorageLocation.resolve(logFileName);
            // Use WebM extension (VP8 codec from Python for browser compatibility)
            Path outputLocation = this.fileStorageLocation.resolve("processed_" + logFileName + ".webm");

            Files.copy(file.getInputStream(), inputLocation, StandardCopyOption.REPLACE_EXISTING);


            // Async Submit (no longer needs pythonScript path - uses HTTP API)
            String taskId = processingManager.submitTask(inputLocation.toString(), outputLocation.toString(), null, isRealtime, modelType, customLabels, confidenceThreshold, autoReport);

            Map<String, String> response = new HashMap<>();
            response.put("taskId", taskId);
            response.put("filePath", inputLocation.toAbsolutePath().toString());
            response.put("message", "Upload successful. Processing started.");
            
            return ResponseEntity.ok(response);

        } catch (IOException ex) {
            return ResponseEntity.status(500).body(Map.of("error", "Upload failed: " + ex.getMessage()));
        }
    }

    @GetMapping("/status/{taskId}")
    public ResponseEntity<VideoProcessingManager.TaskStatus> getStatus(@PathVariable String taskId) {
        VideoProcessingManager.TaskStatus status = processingManager.getStatus(taskId);
        if (status == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(status);
    }
    
    // Need to update signature to return Map<String, Object> instead of Map<String, String>
    @GetMapping("/result/{taskId}")
    public ResponseEntity<Map<String, Object>> getResultLink(@PathVariable String taskId) {
        VideoProcessingManager.TaskStatus status = processingManager.getStatus(taskId);
        if (status == null || status.status != VideoProcessingManager.Status.COMPLETED) {
            return ResponseEntity.badRequest().body(Map.of("error", "Task not completed or not found"));
        }
        Path path = Paths.get(status.outputFilePath);
        String filename = path.getFileName().toString();
        
        // Encode filename for URL
        try {
             filename = java.net.URLEncoder.encode(filename, java.nio.charset.StandardCharsets.UTF_8.toString())
                        .replaceAll("\\+", "%20");
        } catch (Exception e) {}

        Map<String, Object> result = new HashMap<>();
        result.put("downloadUrl", "/api/videos/download/" + filename);
        result.put("aiReport", status.aiReport);
        result.put("incidents", status.incidents);
        
        // Also provide original input video URL for browser playback (H.264 compatible)
        if (status.inputFilePath != null) {
            Path inputPath = Paths.get(status.inputFilePath);
            result.put("inputVideoUrl", "/api/videos/download/" + inputPath.getFileName().toString());
        }
        
        List<String> snapshotUrls = new ArrayList<>();
        if (status.snapshotPaths != null) {
             for(String s : status.snapshotPaths) {
                 snapshotUrls.add("/api/videos/download/" + s);
             }
        }
        result.put("snapshots", snapshotUrls);

        return ResponseEntity.ok(result);
    }

    // NEW: Trigger AI analysis on-demand (for manual report generation)
    @PostMapping("/generate-report/{taskId}")
    public ResponseEntity<Map<String, Object>> generateReport(@PathVariable String taskId) {
        try {
            String aiReport = processingManager.generateReportOnDemand(taskId);
            Map<String, Object> result = new HashMap<>();
            result.put("aiReport", aiReport);
            result.put("success", true);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage(), "success", false));
        }
    }

    // NEW: Update task snapshots from frontend (for Realtime mode)
    @PostMapping("/update-snapshots/{taskId}")
    public ResponseEntity<Map<String, Object>> updateSnapshots(
            @PathVariable String taskId,
            @RequestBody Map<String, Object> request) {
        try {
            @SuppressWarnings("unchecked")
            List<String> snapshotUrls = (List<String>) request.get("snapshotUrls");
            if (snapshotUrls == null || snapshotUrls.isEmpty()) {
                return ResponseEntity.badRequest().body(Map.of("error", "No snapshot URLs provided", "success", false));
            }
            processingManager.updateTaskSnapshots(taskId, snapshotUrls);
            return ResponseEntity.ok(Map.of("success", true, "message", "Snapshots updated"));
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage(), "success", false));
        }
    }


    @GetMapping("/download/{fileName:.+}")
    public ResponseEntity<Resource> downloadFile(@PathVariable String fileName) {
        try {
            Path filePath = this.fileStorageLocation.resolve(fileName).normalize();
            Resource resource = new UrlResource(filePath.toUri());

            if (resource.exists()) {
                // Sanitize filename for Content-Disposition header to avoid Unicode issues in Tomcat
                // We'll use a URLEncoder to ensure special chars (Vietnamese) are safe
                String encodedFileName = java.net.URLEncoder.encode(resource.getFilename(), java.nio.charset.StandardCharsets.UTF_8.toString())
                        .replaceAll("\\+", "%20");

                String contentType = "application/octet-stream";
                String name = resource.getFilename().toLowerCase();
                if (name.endsWith(".mp4")) {
                    contentType = "video/mp4";
                } else if (name.endsWith(".webm")) {
                    contentType = "video/webm";
                } else if (name.endsWith(".avi")) {
                    contentType = "video/x-msvideo";
                } else if (name.endsWith(".jpg") || name.endsWith(".jpeg")) {
                    contentType = "image/jpeg";
                } else if (name.endsWith(".png")) {
                    contentType = "image/png";
                }

                // Use inline for video/images to allow browser playback, attachment for others
                String disposition = contentType.startsWith("video/") || contentType.startsWith("image/") 
                        ? "inline" : "attachment";

                return ResponseEntity.ok()
                        .contentType(MediaType.parseMediaType(contentType))
                        .header(HttpHeaders.CONTENT_DISPOSITION, disposition + "; filename=\"" + encodedFileName + "\"; filename*=UTF-8''" + encodedFileName)
                        .body(resource);
            } else {
                return ResponseEntity.notFound().build();
            }
        } catch (Exception ex) {
            return ResponseEntity.notFound().build();
        }
    }
}
