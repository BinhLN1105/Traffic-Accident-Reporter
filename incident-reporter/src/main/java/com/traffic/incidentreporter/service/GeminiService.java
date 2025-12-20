package com.traffic.incidentreporter.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpEntity;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class GeminiService {

    @Value("${gemini.api.key}")
    private String apiKey;

    @Value("${gemini.model:gemini-1.5-flash}")
    private String modelName;

    private final RestTemplate restTemplate = new RestTemplate();
    private final String BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/";

    // Overload for Web Uploads (Not fully implemented for real API yet, keeping mock/simple)
    public String analyzeImage(MultipartFile image) {
        return "Detected a traffic incident (Simulated for Web Upload).";
    }

    // New: Overload for List of Local Files (Multi-Frame Analysis)
    public String analyzeImage(List<Path> imagePaths) {
        try {
            List<Object> partsList = new java.util.ArrayList<>();
            
            // READ PROMPT FROM FILE
            String promptText = "Bạn là trợ lý AI phân tích tai nạn giao thông. (Default Fallback)";
            try {
                // Read from source resources (allows editing without rebuild in dev)
                Path promptPath = Paths.get("src/main/resources/prompt/prompt.txt").toAbsolutePath();
                if (Files.exists(promptPath)) {
                    promptText = Files.readString(promptPath);
                } else {
                     // Fallback for deployed JAR (if needed later)
                     promptPath = Paths.get("data/prompt.txt"); // Try legacy
                     if (Files.exists(promptPath)) promptText = Files.readString(promptPath);
                }
            } catch (Exception e) {
                System.err.println("Warning: Could not read prompt.txt, using default.");
            }

            // Add Prompt FIRST
            Map<String, Object> textPart = new HashMap<>();
            textPart.put("text", promptText);
            partsList.add(textPart);

            // Add Images
            for (Path path : imagePaths) {
                if (Files.exists(path)) {
                    byte[] imageBytes = Files.readAllBytes(path);
                    String base64Image = Base64.getEncoder().encodeToString(imageBytes);

                    Map<String, Object> inlineData = new HashMap<>();
                    inlineData.put("mime_type", "image/jpeg");
                    inlineData.put("data", base64Image);

                    Map<String, Object> imagePart = new HashMap<>();
                    imagePart.put("inline_data", inlineData);
                    partsList.add(imagePart);
                }
            }

            // --- DEBUG: LOG PAYLOAD DETAILS ---
            System.out.println("📦 PREPARING AI REQUEST 📦");
            System.out.println("   Model: " + modelName);
            System.out.println("   Parts Count: " + partsList.size());
            for (int i = 0; i < partsList.size(); i++) {
                Map<String, Object> p = (Map<String, Object>) partsList.get(i);
                if (p.containsKey("text")) {
                    String t = (String) p.get("text");
                    System.out.println("   - Part " + (i+1) + ": [TEXT] Length=" + t.length() + " chars (Preview: " + (t.length() > 20 ? t.substring(0, 20) + "..." : t) + ")");
                } else if (p.containsKey("inline_data")) {
                    Map<String, Object> inline = (Map<String, Object>) p.get("inline_data");
                    String b64 = (String) inline.get("data");
                    int sizeKB = b64.length() / 1024; // Approx size
                    System.out.println("   - Part " + (i+1) + ": [IMAGE] ~" + sizeKB + " KB");
                }
            }
            System.out.println("-----------------------------------");

            // Execute Request with Retry & Fallback
            try {
                // RETRY LOGIC for Primary Model (3 attempts)
                int retries = 3;
                Exception lastEx = null;
                
                for (int i = 0; i < retries; i++) {
                    try {
                        return callGeminiApi(modelName, partsList);
                    } catch (Exception e) {
                        lastEx = e;
                        String msg = e.getMessage();
                        if (isOverloaded(msg)) {
                            System.out.println("⚠️ Model " + modelName + " overloaded. Retrying (" + (i + 1) + "/" + retries + ")...");
                            Thread.sleep(2000); // 2s delay
                            continue;
                        } 
                        break; // Non-overload error, stop retrying
                    }
                }
                if (lastEx != null) throw lastEx;
                return "Error"; // Should not reach here

            } catch (Exception e) {
                String msg = e.getMessage();
                boolean shouldFallback = msg != null && (msg.contains("503") || msg.contains("429") || msg.contains("Overloaded") || msg.contains("404"));
                
                if (shouldFallback) {
                    System.out.println("⚠️ Primary Model " + modelName + " failed after retries. Entering Fallback Chain...");
                    System.out.println("⚠️ Trying fallback: gemini-1.5-flash-8b");
                    try {
                        return callGeminiApi("gemini-1.5-flash-8b", partsList);
                    } catch (Exception ex2) {
                        System.out.println("⚠️ Fallback (gemini-1.5-flash-8b) failed: " + ex2.getMessage());
                        System.out.println("⚠️ Trying final fallback: gemini-2.5-flash");
                        try {
                            return callGeminiApi("gemini-2.5-flash", partsList);
                        } catch (Exception ex3) {
                             System.err.println("All fallbacks failed.");
                             return handleApiError(ex3);
                        }
                    }
                }
                return handleApiError(e);
            }

        } catch (Exception e) {
            return handleApiError(e);
        }
    }

    private String callGeminiApi(String targetModel, List<Object> partsList) {
        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("contents", List.of(Map.of("parts", partsList)));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(requestBody, headers);

        String url = BASE_URL + targetModel + ":generateContent?key=" + apiKey;
        System.out.println("DEBUG: Calling Gemini API (" + targetModel + ")...");

        ResponseEntity<Map> response = restTemplate.postForEntity(url, entity, Map.class);

        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Map<String, Object> body = response.getBody();
            if (body == null) throw new RuntimeException("Empty Response Body");

            List<Map<String, Object>> candidates = (List<Map<String, Object>>) body.get("candidates");
            if (candidates != null && !candidates.isEmpty()) {
                Map<String, Object> content = (Map<String, Object>) candidates.get(0).get("content");
                if (content != null) {
                    List<Map<String, Object>> resParts = (List<Map<String, Object>>) content.get("parts");
                    if (resParts != null && !resParts.isEmpty()) {
                         Object textObj = resParts.get(0).get("text");
                         return textObj != null ? textObj.toString() : "No text in response";
                    }
                }
            }
        }
        throw new RuntimeException("Empty response from AI");
    }

    private boolean isOverloaded(String msg) {
        return msg != null && (msg.contains("503") || msg.contains("429") || msg.contains("Overloaded"));
    }

    private String handleApiError(Exception e) {
        String msg = e.getMessage();
        boolean isExpectedError = isOverloaded(msg) || (msg != null && (msg.contains("404") || msg.contains("403") || msg.contains("Forbidden")));
        
        if (isExpectedError) {
             // Clean log for expected errors
             System.out.println("⚠️ API Error Handled: " + (msg.length() > 100 ? msg.substring(0, 100) + "..." : msg));
             return "⚠️ <b>Hệ thống:</b> Dịch vụ AI đang quá tải hoặc đạt giới hạn Google API.\n" +
                    "✅ <b>Chế độ Offline:</b> Đang tạo báo cáo dựa trên dữ liệu phát hiện cục bộ.";
        }
        
        // Only print stack trace for unexpected crashes
        e.printStackTrace();
        
        if (msg != null && msg.length() > 200) {
            msg = msg.substring(0, 200) + "... (Check logs for full error)";
        }
        return "Lỗi gọi dịch vụ AI: " + msg;
    }

    // Keep legacy single-path overload for compatibility if needed
    public String analyzeImage(Path imagePath) {
        return analyzeImage(List.of(imagePath));
    }
}
