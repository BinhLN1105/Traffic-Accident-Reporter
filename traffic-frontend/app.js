const API_BASE = 'http://localhost:8080';
let stompClient = null;

// DOM Elements
const connectionStatus = document.getElementById('connection-status');
const incidentList = document.getElementById('incident-list');
const alertBanner = document.getElementById('latest-alert');
const alertTitle = document.getElementById('alert-title');
const alertDesc = document.getElementById('alert-desc');
const countTotalVal = document.getElementById('count-total');
const countTodayVal = document.getElementById('count-today');

let incidentCount = 0;
let todayCount = 0;

function isToday(dateString) {
    const date = new Date(dateString);
    const today = new Date();
    return date.getDate() === today.getDate() &&
           date.getMonth() === today.getMonth() &&
           date.getFullYear() === today.getFullYear();
}

// Connect to WebSocket
function connect() {
    const socket = new SockJS(`${API_BASE}/ws`);
    stompClient = Stomp.over(socket);
    stompClient.debug = null; // Disable debug logs

    stompClient.connect({}, function (frame) {
        setConnected(true);
        console.log('Connected: ' + frame);
        
        // Subscribe to public topic
        stompClient.subscribe('/topic/incidents', function (message) {
            const incident = JSON.parse(message.body);
            handleNewIncident(incident);
        });

    }, function (error) {
        setConnected(false);
        console.error('Connection error:', error);
        // Retry after 5s
        setTimeout(connect, 5000);
    });
}

function setConnected(connected) {
    if (connected) {
        connectionStatus.innerHTML = '<span class="dot"></span> Live';
        connectionStatus.classList.add('connected');
    } else {
        connectionStatus.innerHTML = '<span class="dot"></span> Reconnecting...';
        connectionStatus.classList.remove('connected');
    }
}

// Handle incoming incident
function handleNewIncident(incident) {
    console.log("New Incident:", incident);
    
    // Update Total
    incidentCount++;
    countTotalVal.innerText = incidentCount;

    // Update Today
    if (isToday(incident.timestamp)) {
        todayCount++;
        countTodayVal.innerText = todayCount;
    }

    // 1. Show Alert
    showAlert(incident);

    // 2. Add to List
    addToFeed(incident);
}

function showAlert(incident) {
    alertTitle.innerText = `🔥 ${incident.type || 'ACCIDENT'} DETECTED!`;
    alertDesc.innerText = incident.description || "No description provided.";
    alertBanner.classList.remove('hidden');

    // Auto dismiss after 10s
    setTimeout(() => {
        dismissAlert();
    }, 10000);
}

function dismissAlert() {
    alertBanner.classList.add('hidden');
}

function addToFeed(incident) {
    const card = document.createElement('div');
    card.className = 'incident-card new-item';

    // Format time
    const time = new Date(incident.timestamp).toLocaleTimeString();

    // Determine badge color
    const typeClass = incident.type === 'Fire' ? 'badge-fire' : 'badge-accident';

    card.innerHTML = `
        <img src="${incident.imageUrl ? (API_BASE + incident.imageUrl) : 'https://via.placeholder.com/150'}" alt="Snapshot">
        <div class="info">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                <span class="badge ${typeClass}">${incident.type}</span>
                <span class="time">${time}</span>
            </div>
            <p class="description">${incident.description}</p>
            <span class="location">📍 ${incident.location}</span>
        </div>
    `;

    // Prepend to list
    incidentList.insertBefore(card, incidentList.firstChild);
}

// Initial Load (Optional: Fetch history from API)
async function loadHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/incidents`);
        if(res.ok) {
            const data = await res.json();
            // Data is list of incidents
            // Sort by time desc if not already
            data.reverse().forEach(inc => {
                addToFeed(inc);
                incidentCount++;
                if (isToday(inc.timestamp)) {
                    todayCount++;
                }
            });
            countTotalVal.innerText = incidentCount;
            countTodayVal.innerText = todayCount;
        }
    } catch (e) {
        console.error("Failed to load history", e);
    }
}

// --- REFACTORED VIDEO LOGIC ---

// 1. Triggered on File Selection
function previewFile() {
    const fileInput = document.getElementById('video-input');
    const previewContainer = document.getElementById('video-preview-container');
    const inputVideo = document.getElementById('input-video-preview');
    const analyzeBtn = document.getElementById('analyze-btn');
    const statusDiv = document.getElementById('processing-status');
    const resultDiv = document.getElementById('video-result');

    if (fileInput.files.length > 0) {
        // Clear previous session when new file selected
        sessionStorage.removeItem('lastTaskId');

        const file = fileInput.files[0];
        const fileURL = URL.createObjectURL(file);
        
        // Show Preview
        inputVideo.src = fileURL;
        previewContainer.classList.remove('hidden');
        
        // Enable Analyze Button
        analyzeBtn.disabled = false;
        analyzeBtn.style.opacity = '1';
        analyzeBtn.style.cursor = 'pointer';

        // Hide previous results if any
        statusDiv.classList.add('hidden');
        resultDiv.classList.add('hidden');
    }
}

// 2. Triggered on "Run Analysis" Click
async function startAnalysis() {
    const fileInput = document.getElementById('video-input');
    const analyzeBtn = document.getElementById('analyze-btn');
    const statusDiv = document.getElementById('processing-status');
    const resultDiv = document.getElementById('video-result');
    const statusText = document.getElementById('status-text');
    const progressBar = document.getElementById('progress-bar');
    const aiReportContainer = document.getElementById('ai-report-container');

    if (fileInput.files.length === 0) return;

    const file = fileInput.files[0];

    // UI Updates
    analyzeBtn.disabled = true; // Prevent double click
    analyzeBtn.innerText = "Processing...";
    statusDiv.classList.remove('hidden');
    resultDiv.classList.add('hidden'); // Ensure result is hidden
    aiReportContainer.classList.add('hidden'); // Reset report
    
    // NOTE: We do NOT hide video-preview-container here anymore, so user can watch original video.
    
    progressBar.style.width = '0%';
    progressBar.innerText = '0%';
    statusText.innerText = "Uploading to Cloud...";

    const formData = new FormData();
    formData.append("file", file);

    try {
        // Step 1: Upload
        const res = await fetch(`${API_BASE}/api/videos/process`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            const data = await res.json();
            console.log("Upload Success. Task ID:", data.taskId);
            
            // SAVE SESSION
            sessionStorage.setItem('lastTaskId', data.taskId);

            statusText.innerText = "AI Analysis in Progress...";
            
            // Step 2: Start Polling
            pollStatus(data.taskId);
            
        } else {
            const err = await res.json();
            alert("Upload failed: " + (err.error || "Unknown Error"));
            statusDiv.classList.add('hidden');
            analyzeBtn.disabled = false;
            analyzeBtn.innerText = "Run Analysis ⚡";
        }
    } catch (e) {
        console.error("Upload error", e);
        alert("Connection Failed! Is the backend running?");
        statusDiv.classList.add('hidden');
        analyzeBtn.disabled = false;
        analyzeBtn.innerText = "Run Analysis ⚡";
    }
}

// Reuse pollStatus but update UI reset logic
async function pollStatus(taskId) {
    const statusDiv = document.getElementById('processing-status');
    const statusText = document.getElementById('status-text');
    const progressBar = document.getElementById('progress-bar');
    
    const resultDiv = document.getElementById('video-result');
    const processedVideo = document.getElementById('processed-video');
    const downloadLink = document.getElementById('download-link');
    const analyzeBtn = document.getElementById('analyze-btn');
    const previewContainer = document.getElementById('video-preview-container');
    const inputVideo = document.getElementById('input-video-preview');
    const aiReportContainer = document.getElementById('ai-report-container');
    const aiReportText = document.getElementById('ai-report-text');

    try {
        const res = await fetch(`${API_BASE}/api/videos/status/${taskId}`);
        
        // Handle Task Not Found (e.g., Server Restarted)
        if (res.status === 404) {
            console.warn("Task not found (404). Server might have restarted.");
            sessionStorage.removeItem('lastTaskId');
            alert("Session expired or server restarted. Please upload the video again.");
            
            // Reset UI
            statusDiv.classList.add('hidden');
            analyzeBtn.disabled = false;
            analyzeBtn.innerText = "Run Analysis ⚡";
            return; // Stop polling
        }

        if (!res.ok) throw new Error("Status check failed");
        
        const status = await res.json();
        const progress = status.progress || 0;
        
        // Update Bar
        progressBar.style.width = progress + '%';
        progressBar.innerText = progress + '%';

        if (status.status === 'COMPLETED') {
            // Success
            statusDiv.classList.add('hidden');
            
            // KEEP ORIGINAL PREVIEW VISIBLE (Side-by-Side Comparison)
            // previewContainer.classList.add('hidden'); // REMOVED
            // inputVideo.pause(); // Optional: Keep it playing or pause it. Let's pause it to focus on result? No, user might want to compare.
             
            resultDiv.classList.remove('hidden');
            
            // Get Result Link
            const linkRes = await fetch(`${API_BASE}/api/videos/result/${taskId}`);
            const linkData = await linkRes.json();
            
            processedVideo.src = API_BASE + linkData.downloadUrl;
            downloadLink.href = API_BASE + linkData.downloadUrl;

            // Show AI Report if available
            if (linkData.aiReport) {
                aiReportContainer.classList.remove('hidden');
                aiReportText.innerHTML = linkData.aiReport;
            } else {
                aiReportContainer.classList.add('hidden');
            }

            // --- SHOW DETAILED INCIDENTS TABLE ---
            // Create or clear table container
            let tableContainer = document.getElementById('incidents-table-container');
            if (!tableContainer) {
                tableContainer = document.createElement('div');
                tableContainer.id = 'incidents-table-container';
                tableContainer.className = 'video-preview-box';
                tableContainer.style.marginTop = '15px';
                // Add after video
                const videoBox = document.getElementById('processed-video').parentNode;
                videoBox.parentNode.insertBefore(tableContainer, videoBox.nextSibling);
            }

            if (linkData.incidents && linkData.incidents.length > 0) {
                let html = `
                    <h4 style="margin-bottom:10px; color:var(--text-primary);">📊 Detected Events</h4>
                    <table style="width:100%; border-collapse: collapse; color: var(--text-secondary); font-size: 0.9rem;">
                        <tr style="border-bottom: 2px solid var(--border-color); text-align: left;">
                            <th style="padding: 8px;">Time (s)</th>
                            <th style="padding: 8px;">Event Type</th>
                            <th style="padding: 8px;">Confidence</th>
                        </tr>
                `;
                
                // Show max 10 items to prevent overflow
                linkData.incidents.slice(0, 10).forEach(inc => {
                    const badgeClass = (inc.label.toLowerCase().includes('accident') || inc.label.toLowerCase().includes('fire')) ? 'badge-fire' : 'badge-accident';
                    html += `
                        <tr style="border-bottom: 1px solid rgba(255,255,255,0.1);">
                            <td style="padding: 8px;">${inc.time.toFixed(2)}s</td>
                            <td style="padding: 8px;"><span class="badge ${badgeClass}">${inc.label}</span></td>
                            <td style="padding: 8px;">${(inc.confidence * 100).toFixed(1)}%</td>
                        </tr>
                    `;
                });
                
                html += `</table>`;
                if (linkData.incidents.length > 10) {
                    html += `<p style="padding:8px; font-style:italic; opacity:0.7;">...and ${linkData.incidents.length - 10} more events.</p>`;
                }
                tableContainer.innerHTML = html;
            } else {
                tableContainer.innerHTML = `<p style="color: grey; font-style: italic; padding: 10px;">✅ No accidents or significant events detected in this footage.</p>`;
            }

            // Reset Button
            analyzeBtn.disabled = false;
            analyzeBtn.innerText = "Run Analysis ⚡";

        } else if (status.status === 'FAILED') {
            alert("Processing Failed: " + status.message);
            statusDiv.classList.add('hidden');
            analyzeBtn.disabled = false;
            analyzeBtn.innerText = "Run Analysis ⚡";
        } else {
            // Still Processing
            statusText.innerText = `Analyzing Footage... (${progress}%)`;
            setTimeout(() => pollStatus(taskId), 1000); 
        }

    } catch (e) {
        console.error("Polling error", e);
        setTimeout(() => pollStatus(taskId), 3000);
    }
}

// Init
// connect(); // Start WebSocket
// loadHistory(); // Load old items

// Ensure DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    connect();
    loadHistory();

    // Check for active analysis session
    const lastTaskId = sessionStorage.getItem('lastTaskId');
    if (lastTaskId) {
        console.log("Restoring session for Task ID:", lastTaskId);
        
        // Restore UI state for analysis
        document.getElementById('analyze-btn').disabled = true;
        document.getElementById('analyze-btn').innerText = "Restoring Session...";
        document.getElementById('processing-status').classList.remove('hidden');
        document.getElementById('video-result').classList.add('hidden');
        
        // Resume polling
        pollStatus(lastTaskId);
    }
});
