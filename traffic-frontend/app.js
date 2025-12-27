const API_BASE = 'http://localhost:8080';
const PYTHON_API_BASE = 'http://localhost:5000'; // Python Server
let stompClient = null;
let pc = null; // WebRTC PeerConnection

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

// --- WEBRTC LOGIC ---

async function startWebRTC(jobId, inputPath) {
    console.log("Starting WebRTC for Job:", jobId, "Path:", inputPath);
    
    // 1. Notify Python to Prepare Job (since we uploaded to Java)
    try {
        const initRes = await fetch(`${PYTHON_API_BASE}/process`, {
            method: 'POST',
            body: JSON.stringify({
                // Python expects 'inputPath' to map jobId
                inputPath: inputPath,
                realtime: true 
            }),
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!initRes.ok) {
            console.error("Failed to init job on Python server");
            return;
        }
        
        const initData = await initRes.json();
        const pythonJobId = initData.jobId; // Might be new UUID, or we force it? 
        // Python generates new UUID in current code. 
        // Let's use the Python-generated ID for WebRTC signaling to be safe.
        // Or better: ensure we use the same ID? 
        // Current server.py logic: generates NEW UUID.
        // We will use the ID returned by Python for the WebRTC offer.
        console.log("Python Job ID:", pythonJobId);
        
        // 2. Start WebRTC with Python Job ID
        const configuration = {
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        };
        
        if (pc) pc.close();
        pc = new RTCPeerConnection(configuration);

        const videoElem = document.getElementById('webrtc-video');
        
        pc.ontrack = (event) => {
            console.log("Stream received!");
            if (event.streams && event.streams[0]) {
                videoElem.srcObject = event.streams[0];
                videoElem.play().catch(e => console.error("Auto-play error", e));
            }
        };
        
        pc.addTransceiver('video', { direction: 'recvonly' });
        
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        
        // Send Offer
        const response = await fetch(`${PYTHON_API_BASE}/offer`, {
            method: 'POST',
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type,
                jobId: pythonJobId // Use Python's ID
            }),
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) throw new Error("Signaling failed");
        
        const answer = await response.json();
        await pc.setRemoteDescription(answer);
        console.log("WebRTC Connected!");
        
    } catch (e) {
        console.error("WebRTC Error:", e);
        alert("Failed to connect to AI Stream");
    }
}

function stopWebRTC() {
    if (pc) {
        pc.close();
        pc = null;
    }
    const videoElem = document.getElementById('webrtc-video');
    if (videoElem) {
        videoElem.srcObject = null;
    }
}

// --- APP LOGIC ---

function handleNewIncident(incident) {
    console.log("New Incident:", incident);
    incidentCount++;
    countTotalVal.innerText = incidentCount;
    if (isToday(incident.timestamp)) {
        todayCount++;
        countTodayVal.innerText = todayCount;
    }
    showAlert(incident);
    addToFeed(incident);
}

function showAlert(incident) {
    alertTitle.innerText = `🔥 ${incident.type || 'ACCIDENT'} DETECTED!`;
    alertDesc.innerText = incident.description || "No description provided.";
    alertBanner.classList.remove('hidden');
    setTimeout(() => { dismissAlert(); }, 10000);
}

function dismissAlert() {
    alertBanner.classList.add('hidden');
}

function addToFeed(incident) {
    const card = document.createElement('div');
    card.className = 'incident-card new-item';
    const time = new Date(incident.timestamp).toLocaleTimeString();
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
    incidentList.insertBefore(card, incidentList.firstChild);
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

// Initial Load
async function loadHistory() {
    console.log("Loading history from API...");
    try {
        const res = await fetch(`${API_BASE}/api/incidents`);
        if(res.ok) {
            const data = await res.json();
            console.log("History loaded:", data.length, "items");
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
        } else {
             console.error("Failed to load history: HTTP", res.status);
        }
    } catch (e) {
        console.error("Failed to load history", e);
    }
}

function previewFile() {
    const fileInput = document.getElementById('video-input');
    const previewContainer = document.getElementById('video-preview-container');
    const inputVideo = document.getElementById('input-video-preview');
    const statusDiv = document.getElementById('processing-status');
    const resultDiv = document.getElementById('video-result');

    if (fileInput.files.length > 0) {
        sessionStorage.removeItem('lastTaskId');
        const file = fileInput.files[0];
        const fileURL = URL.createObjectURL(file);
        
        inputVideo.src = fileURL;
        previewContainer.classList.remove('hidden');
        
        const optionsDiv = document.getElementById('analysis-options');
        const modelDiv = document.getElementById('model-selection-container');
        optionsDiv.classList.remove('hidden');
        optionsDiv.style.display = 'flex';
        modelDiv.classList.remove('hidden');

        statusDiv.classList.add('hidden');
        resultDiv.classList.add('hidden');
        stopWebRTC();
    }
}

async function startAnalysis(isRealtime) {
    const fileInput = document.getElementById('video-input');
    const statusDiv = document.getElementById('processing-status');
    const resultDiv = document.getElementById('video-result');
    const statusText = document.getElementById('status-text');
    const progressBar = document.getElementById('progress-bar');
    const aiReportContainer = document.getElementById('ai-report-container');
    const optionsDiv = document.getElementById('analysis-options');

    if (fileInput.files.length === 0) return;

    const file = fileInput.files[0];

    // UI Updates
    optionsDiv.classList.add('hidden'); 
    
    if (isRealtime) {
         statusDiv.classList.add('hidden');
    } else {
        statusDiv.classList.remove('hidden');
        progressBar.style.width = '0%';
        progressBar.innerText = '0%';
        statusText.innerText = "Uploading & Analyzing...";
    }

    resultDiv.classList.add('hidden');
    aiReportContainer.classList.add('hidden');
    
    // --- UPLOAD TO JAVA (SPRING BOOT) ---
    const formData = new FormData();
    const modelType = document.getElementById('model-select').value;
    formData.append("file", file);
    formData.append("realtime", isRealtime);
    formData.append("modelType", modelType);

    try {
        console.log("Uploading to Spring Boot...");
        const res = await fetch(`${API_BASE}/api/videos/process`, {
            method: 'POST',
            body: formData,
             headers: { 'Accept': 'application/json' }
        });
        
        if (res.ok) {
            const data = await res.json();
            console.log("Spring Boot Response:", data);
            // Expected: { taskId: "...", filePath: "...", message: "..." }
            
            if (isRealtime) {
                // --- REALTIME MODE ---
                // Switch to Live View
                 const liveSection = document.getElementById('live-stream-section');
                 const uploadInputSection = document.getElementById('upload-input-section');
                 const previewContainer = document.getElementById('video-preview-container');
                 
                 uploadInputSection.classList.add('hidden');
                 previewContainer.classList.add('hidden');
                 liveSection.classList.remove('hidden');
                 
                 // Check if filePath is present (from our Java update)
                 if (data.filePath) {
                     startWebRTC(data.taskId, data.filePath);
                 } else {
                     alert("Server did not return file path. Make sure Java controller is updated.");
                 }
                
            } else {
                // --- BATCH MODE ---
                sessionStorage.setItem('lastTaskId', data.taskId);
                statusText.innerText = "Batch Analysis in Progress...";
                pollStatus(data.taskId);
            }
            
        } else {
             const err = await res.json();
             alert("Error: " + (err.error || "Upload Failed"));
             optionsDiv.classList.remove('hidden'); 
        }

    } catch (e) {
        console.error("Upload error", e);
        alert("Connection Failed!");
        optionsDiv.classList.remove('hidden');
    }
}

async function pollStatus(taskId) {
    // ... [Same Polling Logic as Before] ...
    // For brevity, keeping it mostly same, but need to include it.
    
    const statusDiv = document.getElementById('processing-status');
    const statusText = document.getElementById('status-text');
    const progressBar = document.getElementById('progress-bar');
    const resultDiv = document.getElementById('video-result');
    const processedVideo = document.getElementById('processed-video');
    const downloadLink = document.getElementById('download-link');
    const optionsDiv = document.getElementById('analysis-options'); 

    const aiReportContainer = document.getElementById('ai-report-container');
    const aiReportText = document.getElementById('ai-report-text');

    try {
        const res = await fetch(`${API_BASE}/api/videos/status/${taskId}`);
        if (res.status === 404) {
            sessionStorage.removeItem('lastTaskId');
            alert("Session expired.");
            statusDiv.classList.add('hidden');
            if(optionsDiv) optionsDiv.classList.remove('hidden');
            return;
        }

        if (!res.ok) throw new Error("Status check failed");
        
        const status = await res.json();
        const progress = status.progress || 0;
        progressBar.style.width = progress + '%';
        progressBar.innerText = progress + '%';

        if (status.status === 'COMPLETED') {
            statusDiv.classList.add('hidden');
            const uploadInputSection = document.getElementById('upload-input-section');
            uploadInputSection.classList.remove('hidden');
            if(optionsDiv) optionsDiv.classList.remove('hidden');
            
            resultDiv.classList.remove('hidden');
            
            const linkRes = await fetch(`${API_BASE}/api/videos/result/${taskId}`);
            const linkData = await linkRes.json();
            
            processedVideo.src = API_BASE + linkData.downloadUrl;
            downloadLink.href = API_BASE + linkData.downloadUrl;

            // Render Snapshots
            const gallery = document.getElementById('snapshot-gallery');
            gallery.innerHTML = ''; // Clear prev
            if (linkData.snapshots && linkData.snapshots.length > 0) {
                const labels = ["Before", "During", "After"];
                linkData.snapshots.forEach((url, idx) => {
                    const wrap = document.createElement('div');
                    wrap.style.textAlign = 'center';
                    
                    const label = (idx < 3) ? labels[idx] : `Snapshot ${idx+1}`;
                    
                    wrap.innerHTML = `
                        <img src="${API_BASE + url}" style="width:160px; height:auto; border-radius:4px; border:1px solid #555;">
                        <div style="font-size:0.8em; color:#aaa; margin-top:2px;">${label}</div>
                    `;
                    gallery.appendChild(wrap);
                });
            }

            if (linkData.aiReport) {
                aiReportContainer.classList.remove('hidden');
                aiReportText.innerHTML = linkData.aiReport;
            } else {
                aiReportContainer.classList.add('hidden');
            }
        } else if (status.status === 'FAILED') {
            alert("Processing Failed");
            statusDiv.classList.add('hidden');
            if(optionsDiv) optionsDiv.classList.remove('hidden');
        } else {
            statusText.innerText = `Analyzing... (${progress}%)`;
            setTimeout(() => pollStatus(taskId), 1000); 
        }

    } catch (e) {
        setTimeout(() => pollStatus(taskId), 3000);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    connect(); // Restore Connection
    loadHistory();
    const lastTaskId = sessionStorage.getItem('lastTaskId');
    if (lastTaskId) { pollStatus(lastTaskId); }
});

function switchMode(mode) {
    const uploadInputSection = document.getElementById('upload-input-section');
    const optionsDiv = document.getElementById('analysis-options');
    const previewContainer = document.getElementById('video-preview-container');
    const resultDiv = document.getElementById('video-result');
    const liveSection = document.getElementById('live-stream-section');
    const uploadBtn = document.getElementById('mode-upload-btn');
    const liveBtn = document.getElementById('mode-live-btn');

    if (mode === 'live') {
        uploadInputSection.classList.add('hidden');
        if(optionsDiv) optionsDiv.classList.add('hidden');
        previewContainer.classList.add('hidden');
        resultDiv.classList.add('hidden');
        liveSection.classList.remove('hidden');
        liveBtn.classList.remove('btn-secondary');
        liveBtn.classList.add('btn-primary');
        uploadBtn.classList.remove('btn-primary');
        uploadBtn.classList.add('btn-secondary');
    } else {
        stopWebRTC();
        uploadInputSection.classList.remove('hidden');
        if(optionsDiv && document.getElementById('video-input').files.length > 0) {
             optionsDiv.classList.remove('hidden');
        }
        liveSection.classList.add('hidden');
        uploadBtn.classList.remove('btn-secondary');
        uploadBtn.classList.add('btn-primary');
        liveBtn.classList.remove('btn-primary');
        liveBtn.classList.add('btn-secondary');
        if (document.getElementById('video-input').files.length > 0) {
             previewContainer.classList.remove('hidden');
        }
    }
}
