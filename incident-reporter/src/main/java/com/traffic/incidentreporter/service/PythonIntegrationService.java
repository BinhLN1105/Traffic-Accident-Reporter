package com.traffic.incidentreporter.service;

import org.springframework.stereotype.Service;
import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;

@Service
public class PythonIntegrationService {

    public boolean processVideo(String inputPath, String outputPath) {
        try {
            // Assume 'video_processor.py' is in 'traffic-ai-client' folder
            // Adjust path based on actual deployment
            String pythonScript = "d:/ProjectHTGTTM_CarTrafficReport/traffic-ai-client/video_processor.py";
            
            ProcessBuilder pb = new ProcessBuilder(
                "python", 
                pythonScript, 
                "--input", inputPath, 
                "--output", outputPath
            );
            
            pb.directory(new File("d:/ProjectHTGTTM_CarTrafficReport/traffic-ai-client"));
            pb.redirectErrorStream(true);
            
            System.out.println("Starting Python script: " + pythonScript);
            System.out.println("Arguments: " + inputPath + " -> " + outputPath);
            
            Process process = pb.start();
            
            // Log output
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line;
            while ((line = reader.readLine()) != null) {
                System.out.println("[Python] " + line);
            }
            
            int exitCode = process.waitFor();
            System.out.println("Python script finished with exit code: " + exitCode);
            return exitCode == 0;
            
        } catch (Exception e) {
            e.printStackTrace();
            return false;
        }
    }
}
