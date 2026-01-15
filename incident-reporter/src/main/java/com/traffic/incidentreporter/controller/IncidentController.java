package com.traffic.incidentreporter.controller;

import com.traffic.incidentreporter.entity.Incident;
import com.traffic.incidentreporter.repository.IncidentRepository;
import com.traffic.incidentreporter.service.GeminiService;
import lombok.RequiredArgsConstructor;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;


import java.time.LocalDateTime;
import java.util.List;

@RestController
@RequestMapping("/api/incidents")
@RequiredArgsConstructor
@CrossOrigin(origins = "*") // Allow React to access
public class IncidentController {

    private final IncidentRepository incidentRepository;
    private final GeminiService geminiService;
    private final SimpMessagingTemplate messagingTemplate;

    @PostMapping
    public ResponseEntity<Incident> reportIncident(
            @RequestParam("image") MultipartFile image,
            @RequestParam("type") String type,
            @RequestParam("location") String location
    ) {
        // 1. Analyze with Gemini
        String description = geminiService.analyzeImage(image);

        // 2. Save Image
        String fileName = "manual_" + System.currentTimeMillis() + "_" + image.getOriginalFilename();
        try {
            java.nio.file.Path uploadDir = java.nio.file.Paths.get("..", "data").toAbsolutePath().normalize();
            if (!java.nio.file.Files.exists(uploadDir)) {
                java.nio.file.Files.createDirectories(uploadDir);
            }
            java.nio.file.Path targetLocation = uploadDir.resolve(fileName);
            java.nio.file.Files.copy(image.getInputStream(), targetLocation, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        } catch (Exception e) {
            e.printStackTrace();
        }

        String imageUrl = "/api/videos/download/" + fileName; // Reusing VideoController's serve endpoint

        // 3. Create Entity
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
        
        incident.setType(type);
        incident.setLocation(location);
        incident.setTimestamp(LocalDateTime.now());
        incident.setDescription(description);
        incident.setImageUrl(imageUrl);
        incident.setAlertSent(false);

        Incident saved = incidentRepository.save(incident);


        // 4. Send WebSocket Alert
        try {
            messagingTemplate.convertAndSend("/topic/incidents", saved);
            saved.setAlertSent(true);
            incidentRepository.save(saved);
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        return ResponseEntity.ok(saved);
    }

    @PostMapping("/report")
    public ResponseEntity<Incident> reportFullIncident(
            @RequestParam("imageBefore") MultipartFile imageBefore,
            @RequestParam("imageDuring") MultipartFile imageDuring,
            @RequestParam("imageAfter") MultipartFile imageAfter,
            @RequestParam("type") String type,
            @RequestParam(value = "description", required = false) String description,
            @RequestParam(value = "video", required = false) MultipartFile video
    ) {
        // 1. Save Images
        String[] fileNames = new String[3];
        MultipartFile[] files = {imageBefore, imageDuring, imageAfter};
        java.util.List<java.nio.file.Path> savedPaths = new java.util.ArrayList<>();
        
        try {
            java.nio.file.Path uploadDir = java.nio.file.Paths.get("..", "data").toAbsolutePath().normalize();
            if (!java.nio.file.Files.exists(uploadDir)) {
                java.nio.file.Files.createDirectories(uploadDir);
            }
            
            for (int i = 0; i < files.length; i++) {
                String name = "snap_" + i + "_" + System.currentTimeMillis() + "_" + files[i].getOriginalFilename();
                java.nio.file.Path target = uploadDir.resolve(name);
                java.nio.file.Files.copy(files[i].getInputStream(), target, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                fileNames[i] = "/api/videos/download/" + name;
                savedPaths.add(target);
            }
        } catch (Exception e) {
            e.printStackTrace();
            return ResponseEntity.internalServerError().build();
        }

        // 1b. Save Video (if provided)
        String videoUrl = null;
        if (video != null && !video.isEmpty()) {
            try {
                String vidName = "vid_" + System.currentTimeMillis() + "_" + video.getOriginalFilename();
                java.nio.file.Path vidTarget = java.nio.file.Paths.get("..", "data").toAbsolutePath().normalize().resolve(vidName);
                java.nio.file.Files.copy(video.getInputStream(), vidTarget, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                videoUrl = "/api/videos/download/" + vidName;
            } catch (Exception e) {
                e.printStackTrace();
            }
        }

        // 2. Analyze with Gemini (Multi-image)
        String aiAnalysis = geminiService.analyzeImage(savedPaths);

        // 3. Create Entity
        Incident incident = new Incident();
        
        // ID Logic
        Long newId = 1L;
        if (!incidentRepository.existsById(1L)) {
            newId = 1L;
        } else {
            Long gapId = incidentRepository.findNextAvailableId();
            newId = (gapId != null) ? gapId : ((incidentRepository.findMaxId() != null) ? incidentRepository.findMaxId() + 1 : 1L);
        }
        incident.setId(newId);
        
        incident.setType(type);
        incident.setTimestamp(LocalDateTime.now());
        incident.setDescription(description != null ? description : "AI Report Generated");
        
        // Set URLs
        incident.setImageUrl(fileNames[1]); // Use 'During' as main thumbnail
        incident.setSnapshotUrls(String.format("[\"%s\", \"%s\", \"%s\"]", fileNames[0], fileNames[1], fileNames[2]));
        incident.setVideoUrl(videoUrl); // Set the video URL
        incident.setAiReport(aiAnalysis);
        incident.setAlertSent(false);

        Incident saved = incidentRepository.save(incident);

        // 4. Send WebSocket Alert
        try {
            messagingTemplate.convertAndSend("/topic/incidents", saved);
            saved.setAlertSent(true);
            incidentRepository.save(saved);
        } catch (Exception e) {
            e.printStackTrace();
        }
        
        return ResponseEntity.ok(saved);
    }

    @GetMapping
    public List<Incident> getAllIncidents() {
        return incidentRepository.findAll();
    }
}
