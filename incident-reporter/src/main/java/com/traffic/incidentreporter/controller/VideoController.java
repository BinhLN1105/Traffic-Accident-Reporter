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
            @RequestParam(value = "modelType", defaultValue = "medium") String modelType) {
        try {
            System.out.println("Received: " + file.getOriginalFilename() + " (Realtime=" + isRealtime + ", Model=" + modelType + ")");
            
            String logFileName = UUID.randomUUID().toString() + "_" + file.getOriginalFilename();
            Path inputLocation = this.fileStorageLocation.resolve(logFileName);
            // Change output extension to .webm for better browser compatibility
            Path outputLocation = this.fileStorageLocation.resolve("processed_" + logFileName + ".webm");

            Files.copy(file.getInputStream(), inputLocation, StandardCopyOption.REPLACE_EXISTING);

            // Async Submit
            String pythonScript = "d:/ProjectHTGTTM_CarTrafficReport/traffic-ai-client/video_processor.py";
            String taskId = processingManager.submitTask(inputLocation.toString(), outputLocation.toString(), pythonScript, isRealtime, modelType);

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
        
        List<String> snapshotUrls = new ArrayList<>();
        if (status.snapshotPaths != null) {
             for(String s : status.snapshotPaths) {
                 snapshotUrls.add("/api/videos/download/" + s);
             }
        }
        result.put("snapshots", snapshotUrls);

        return ResponseEntity.ok(result);
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

                return ResponseEntity.ok()
                        .contentType(MediaType.parseMediaType("video/webm"))
                        .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + encodedFileName + "\"; filename*=UTF-8''" + encodedFileName)
                        .body(resource);
            } else {
                return ResponseEntity.notFound().build();
            }
        } catch (Exception ex) {
            return ResponseEntity.notFound().build();
        }
    }
}
