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
        String fileName = "snapshot_" + System.currentTimeMillis() + "_" + image.getOriginalFilename();
        try {
            java.nio.file.Path uploadDir = java.nio.file.Paths.get("uploads").toAbsolutePath().normalize();
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

    @GetMapping
    public List<Incident> getAllIncidents() {
        return incidentRepository.findAll();
    }
}
