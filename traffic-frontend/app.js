const API_BASE = 'http://localhost:8080';
const PYTHON_API_BASE = 'http://localhost:5000'; // Python Server
let stompClient = null;
let pc = null; // WebRTC PeerConnection
let currentMode = 'batch'; // 'batch' or 'realtime'

// ========== THEME MANAGEMENT ==========
function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    // Update toggle icon
    const icon = document.querySelector('.theme-toggle-icon');
    if (icon) {
        icon.textContent = newTheme === 'dark' ? '🌙' : '☀️';
    }
}

function loadTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    
    // Update toggle icon
    const icon = document.querySelector('.theme-toggle-icon');
    if (icon) {
        icon.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
    }
}

// ========== TOOLTIP FUNCTIONS ==========
let tooltipTimeout;

function showTooltip() {
    clearTimeout(tooltipTimeout);
    const tooltip = document.getElementById('confidence-tooltip');
    if (tooltip) {
        tooltip.classList.remove('hidden');
        tooltip.classList.add('show');
    }
}

function hideTooltip() {
    tooltipTimeout = setTimeout(() => {
        const tooltip = document.getElementById('confidence-tooltip');
        if (tooltip) {
            tooltip.classList.remove('show');
            setTimeout(() => tooltip.classList.add('hidden'), 300);
        }
    }, 200);
}

function toggleTooltip() {
    const tooltip = document.getElementById('confidence-tooltip');
    if (tooltip) {
        if (tooltip.classList.contains('show')) {
            hideTooltip();
        } else {
            showTooltip();
        }
    }
}

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
let allIncidents = []; // Store all incidents for pagination
let displayedCount = 0;
const ITEMS_PER_PAGE = 5;

function isToday(dateString) {
    const date = new Date(dateString);
    const today = new Date();
    return date.getDate() === today.getDate() &&
           date.getMonth() === today.getMonth() &&
           date.getFullYear() === today.getFullYear();
}

// --- PERSISTENCE LOGIC ---
function saveState() {
    const modelSelect = document.getElementById('model-select');
    localStorage.setItem('selectedModel', modelSelect.value);
    
    // Cannot save full path due to security, can only save filename as hint
    // But we can't restore the file object. 
    // We just ensure model persists.
}

function restoreState() {
    const savedModel = localStorage.getItem('selectedModel');
    if (savedModel) {
        document.getElementById('model-select').value = savedModel;
    }
}


// --- WEBRTC LOGIC ---
let currentRealtimeTaskId = null; // NEW: Store Java taskId for AI report generation

async function startWebRTC(javaTaskId, inputPath) {
    console.log("Starting WebRTC for Task:", javaTaskId, "Path:", inputPath);
    
    // Store Java taskId for later use (AI report generation)
    currentRealtimeTaskId = javaTaskId;
    
    // 1. Notify Python to Prepare Job (since we uploaded to Java)
    try {
        const initRes = await fetch(`${PYTHON_API_BASE}/process`, {
            method: 'POST',
            body: JSON.stringify({
                // Python expects 'inputPath' to map jobId
                inputPath: inputPath,
                realtime: true,
                autoReport: document.getElementById('auto-report').checked 
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
                jobId: pythonJobId,
                // Pass jobId to help server locate the correct job
            }),
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) throw new Error("Signaling failed");
        
        const answer = await response.json();
        await pc.setRemoteDescription(answer);
        console.log("WebRTC Connected!");
        
        // Start Polling for Realtime Updates (Snapshots)
        currentRealtimeJobId = pythonJobId;
        pollRealtimeStatus(pythonJobId);
        
    } catch (e) {
        console.error("WebRTC Error:", e);
        alert("Failed to connect to AI Stream");
    }
}

let currentRealtimeJobId = null;
let realtimePollTimeout = null;

async function pollRealtimeStatus(jobId) {
    if (jobId !== currentRealtimeJobId) return; // Stop if changed
    
    try {
        const res = await fetch(`${PYTHON_API_BASE}/status/${jobId}`);
        if (res.ok) {
            const status = await res.json();
            
            // Update UI with snapshots if available
            if (status.snapshot_urls && status.snapshot_urls.length > 0) {
                 updateRealtimeGallery(status.snapshot_urls);
            }
            
            // CHECK FOR AI REPORT in status (Added by Server Fix)
            if (status.aiReport && status.incidentId) {
                console.log("AI Report Found in Job Status:", status.incidentId);
                // Inject report directly into UI logic
                // We create a mock 'incident' object and load it
                if (!window.hasShownRealtimeReport) {
                    window.hasShownRealtimeReport = true; // Avoid repeated alerts
                    
                    const reportData = {
                         timestamp: new Date().toISOString(),
                         type: 'Accident', // Logic could be improved to get from status
                         location: 'Live Stream',
                         aiReport: status.aiReport,
                         snapshotUrls: JSON.stringify(status.snapshot_urls || []),
                         // videoUrl: ... (if available)
                         description: "Auto-detected by Realtime AI"
                    };
                    
                    // Show Notification
                    showAlert(reportData);
                    
                    // Auto-open Report view
                    // loadIncidentIntoView(reportData); 
                    // Or properly populate 'Live Session Report'
                     const reportContainer = document.getElementById('live-report-container');
                     const reportContent = document.getElementById('live-report-content');
                     reportContent.textContent = status.aiReport;
                     reportContainer.classList.remove('hidden');
                     
                     // HIDE the manual create button since we have the report
                     const reportSection = document.getElementById('live-report-section');
                     if(reportSection) reportSection.classList.add('hidden');
                }
            }
            
            // Check if job ended or failed
            if (status.status === 'FAILED') {
                console.error("Stream Job Failed:", status.message);
            }
        }
    } catch (e) {
        console.error("Poll Error:", e);
    }
    
    // Poll every 2 seconds
    realtimePollTimeout = setTimeout(() => pollRealtimeStatus(jobId), 2000);
}

function updateRealtimeGallery(urls) {
    // Target the specific Live Gallery, fallback to main if not found
    let gallery = document.getElementById('live-snapshot-gallery');
    if (!gallery) gallery = document.getElementById('snapshot-gallery');
    
    // resultDiv removal is not needed for Live mode as we have dedicated area
    // const resultDiv = document.getElementById('video-result');
    // resultDiv.classList.remove('hidden'); 
    
    // Optimization: Only append NEW images to avoid flicker/refresh feel
    const currentCount = gallery.childElementCount;
    if (urls.length <= currentCount) return;
    
    // Group by 3 for label logic logic: Before, During, After, Before...
    const labels = ["Before", "During", "After"];
    
    // Start loop from currentCount to only add new ones
    for (let i = currentCount; i < urls.length; i++) {
        const url = urls[i];
        const wrap = document.createElement('div');
        wrap.style.textAlign = 'center';
        
        // Incident Index changes every 3 images
        const incidentIdx = Math.floor(i / 3);
        const typeIdx = i % 3;
        const label = labels[typeIdx]; 
        
        const fullUrl = `${PYTHON_API_BASE}${url}`;
        
        wrap.innerHTML = `
            <img src="${fullUrl}" style="width:160px; height:auto; border-radius:4px; border:1px solid #555; cursor: pointer;" onclick="openLightbox(this.src)">
            <div style="font-size:0.8em; color:#aaa; margin-top:2px;">#${incidentIdx+1} ${label}</div>
        `;
        // Append new item to end
        gallery.appendChild(wrap);
    }
    
    // Calculate scroll: if user was at bottom, keep at bottom?
    // For now, just scroll to bottom to show new content
    gallery.scrollTop = gallery.scrollHeight;
}

function stopWebRTC() {
    clearTimeout(realtimePollTimeout); // Stop Polling
    currentRealtimeJobId = null;
    
    if (pc) {
        pc.close();
        pc = null;
    }
    const videoElem = document.getElementById('webrtc-video');
    if (videoElem) {
        videoElem.srcObject = null;
    }
    
    // Enable/Disable buttons (with null checks for batch mode compatibility)
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    
    // Show the Create Report button after stopping, BUT ONLY if no report exists yet
    const reportSection = document.getElementById('live-report-section');
    const reportContainer = document.getElementById('live-report-container');
    
    // Check if report container is visible and has content
    const hasReport = !reportContainer.classList.contains('hidden') && 
                      document.getElementById('live-report-content').textContent.trim().length > 0;
                      
    if(reportSection && !hasReport) {
         reportSection.classList.remove('hidden');
    } else if (reportSection) {
         reportSection.classList.add('hidden');
    }
}

async function generateLiveReport() {
    console.log("Generating AI-powered Live Report...");
    
    const reportContainer = document.getElementById('live-report-container');
    const reportContent = document.getElementById('live-report-content');
    const gallery = document.getElementById('live-snapshot-gallery');
    const images = gallery.getElementsByTagName('img');
    
    // Check if we have snapshots and a valid task ID
    if (images.length === 0) {
        reportContent.textContent = "❌ No snapshots captured yet. Please wait for incident detection.";
        reportContainer.classList.remove('hidden');
        return;
    }
    
    if (!currentRealtimeTaskId) {
        reportContent.textContent = "❌ No active Realtime session. Please start a stream first.";
        reportContainer.classList.remove('hidden');
        return;
    }
    
    // Show loading state
    reportContent.textContent = "⏳ Syncing snapshots and generating AI report...";
    reportContainer.classList.remove('hidden');
    
    try {
        // 1. Collect snapshot URLs from gallery images
        const snapshotUrls = [];
        for (let img of images) {
            // img.src is full URL like http://localhost:5000/data/xxx.jpg
            // We need just the path part: /data/xxx.jpg
            const url = new URL(img.src);
            snapshotUrls.push(url.pathname); // e.g., /data/xxx.jpg
        }
        console.log("Snapshot URLs to sync:", snapshotUrls);
        
        // 2. Sync snapshots with Java backend
        const syncRes = await fetch(`${API_BASE}/api/videos/update-snapshots/${currentRealtimeTaskId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ snapshotUrls: snapshotUrls })
        });
        
        if (!syncRes.ok) {
            throw new Error("Failed to sync snapshots with backend");
        }
        
        // 3. Call existing generateReport API
        reportContent.textContent = "⏳ AI is analyzing the incident...";
        const reportRes = await fetch(`${API_BASE}/api/videos/generate-report/${currentRealtimeTaskId}`, {
            method: 'POST'
        });
        
        if (!reportRes.ok) {
            throw new Error("Failed to generate AI report");
        }
        
        const reportData = await reportRes.json();
        
        if (reportData.success && reportData.aiReport) {
            // 4. Display the AI report
            reportContent.textContent = reportData.aiReport;
            console.log("AI Report generated successfully!");
        } else {
            throw new Error(reportData.error || "Unknown error");
        }
        
    } catch (error) {
        console.error("Live report generation failed:", error);
        reportContent.textContent = `❌ Error: ${error.message}\n\nFallback: Static report generated.\n\n` + generateStaticReport(images.length);
    }
    
    // Scroll to report
    reportContainer.scrollIntoView({ behavior: 'smooth' });
}

// Helper: Generate static fallback report
function generateStaticReport(totalSnaps) {
    const now = new Date();
    return `📊 REALTIME SESSION REPORT\n📅 Date: ${now.toLocaleDateString()}\n⏰ Time: ${now.toLocaleTimeString()}\n\n🔢 Summary:\n- Total Snapshots: ${totalSnaps}\n- Estimated Incidents: ${Math.round(totalSnaps / 3) || 0}\n\nℹ️ AI analysis unavailable. Please check backend connection.`;
}

// --- APP LOGIC ---

function handleNewIncident(incident) {
    console.log("New Incident:", incident);
    
    // Add to allIncidents array at the beginning (newest first)
    allIncidents.unshift(incident);
    
    incidentCount++;
    countTotalVal.innerText = incidentCount;
    if (isToday(incident.timestamp)) {
        todayCount++;
        countTodayVal.innerText = todayCount;
    }
    showAlert(incident);
    addToFeed(incident, true); // Mark as new for animation
    displayedCount++; // Increment since we added a new item
    updateLoadMoreButton(); // Update button text
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

function addToFeed(incident, isNew = false) {
    const card = document.createElement('div');
    card.className = 'incident-card' + (isNew ? ' new-item' : '');
    const time = new Date(incident.timestamp).toLocaleTimeString();
    
    // Determine Badge Color
    let typeClass = 'badge-accident';
    const typeLower = (incident.type || '').toLowerCase();
    const isNoAccident = typeLower.includes('no accident') || typeLower.includes('safe');
    
    if (isNoAccident) {
        typeClass = 'badge-safe';
    } else if (typeLower === 'fire') {
        typeClass = 'badge-fire';
    }
    
    // Truncate description
    const description = incident.description || incident.aiReport || 'No description';
    const shortDesc = description.length > 100 ? description.substring(0, 100) + '...' : description;
    const hasMore = description.length > 100;

    // Conditionally render image
    // Skip image if "No Accident" or if URL is invalid/fallback
    let imgHtml = '';
    const hasValidImage = incident.imageUrl && 
                          incident.imageUrl !== 'null' && 
                          !incident.imageUrl.includes('/null') &&
                          !incident.imageUrl.includes('no-image.png');

    if (!isNoAccident && hasValidImage) {
         imgHtml = `<img src="${API_BASE + incident.imageUrl}" alt="Snapshot" onclick="event.stopPropagation(); openLightbox(this.src)" style="cursor: pointer;">`;
    }

    // Handle Location null
    const locationDisplay = incident.location && incident.location !== 'null' ? incident.location : 'Detected from Video';

    card.innerHTML = `
        ${imgHtml}
        <div class="info">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                <span class="badge ${typeClass}">${incident.type}</span>
                <span class="time">${time}</span>
            </div>
            <p class="description" data-full="${description.replace(/"/g, '&quot;')}">${shortDesc}</p>
            ${hasMore ? '<button class="read-more-btn" onclick="event.stopPropagation(); toggleDescription(this)">Xem chi tiết ▼</button>' : ''}
            <span class="location">📍 ${locationDisplay}</span>
        </div>
    `;
    // Make card clickable for history playback
    card.onclick = () => loadIncidentIntoView(incident);
    
    // If new real-time incident, add to top. Otherwise append to maintain order
    if (isNew) {
        incidentList.insertBefore(card, incidentList.firstChild);
    } else {
        incidentList.appendChild(card);
    }
}

// Toggle description expand/collapse
function toggleDescription(btn) {
    const descElement = btn.previousElementSibling;
    const fullText = descElement.getAttribute('data-full');
    const currentText = descElement.textContent;
    
    if (btn.textContent.includes('▼')) {
        descElement.textContent = fullText;
        btn.textContent = 'Thu gọn ▲';
    } else {
        const shortText = fullText.substring(0, 100) + '...';
        descElement.textContent = shortText;
        btn.textContent = 'Xem chi tiết ▼';
    }
}

// --- HISTORY PLAYBACK ---
function loadIncidentIntoView(incident) {
    console.log("Loading history item:", incident);
    
    // 1. Hide Input/Live sections, show Result
    document.getElementById('upload-input-section').classList.add('hidden');
    document.getElementById('live-stream-section').classList.add('hidden');
    document.getElementById('video-preview-container').classList.add('hidden');
    document.getElementById('processing-status').classList.add('hidden');
    document.getElementById('analysis-options').classList.add('hidden'); // Hide buttons
    
    const resultDiv = document.getElementById('video-result');
    resultDiv.classList.remove('hidden');
    
    // 2. Populate Report Area
    const aiReportContainer = document.getElementById('ai-report-container');
    const aiReportText = document.getElementById('ai-report-text');
    const reportSnapshots = document.getElementById('report-snapshots');
    
    // Hide "Create Report" button since it's already done
    document.getElementById('create-report-section').classList.add('hidden'); 
    
    if (incident.description || incident.aiReport) {
         aiReportContainer.classList.remove('hidden');
         const reportContent = incident.aiReport || incident.description || "No detailed report available.";
         const header = `Report Date: ${new Date(incident.timestamp).toLocaleString()}\n\n`;
         
         // Clean markdown and set up collapsible view
         const cleanedContent = cleanMarkdown(reportContent);
         const summary = extractSummary(cleanedContent);
         
         const reportSummary = document.getElementById('ai-report-summary');
         const toggleBtn = document.getElementById('toggle-report-btn');
         
         reportSummary.textContent = summary;
         aiReportText.textContent = header + cleanedContent;
         
         // Reset to summary view
         aiReportText.classList.add('hidden');
         reportSummary.classList.remove('hidden');
         toggleBtn.textContent = 'Xem chi tiết báo cáo ▼';
         toggleBtn.style.display = cleanedContent.length > summary.length + 100 ? 'block' : 'none';
         
         // Populate report snapshots for PDF
         reportSnapshots.innerHTML = '';
         
         // NEW: Parse snapshotUrls if available
         if (incident.snapshotUrls) {
             try {
                 const snapshotArray = JSON.parse(incident.snapshotUrls);
                 snapshotArray.forEach(url => {
                     if (!url || url.includes('null') || url.includes('no-image')) return;
                     const img = document.createElement('img');
                     img.src = API_BASE + url;
                     img.style.height = '150px';
                     img.style.margin = '5px';
                     reportSnapshots.appendChild(img);
                 });
             } catch (e) {
                 console.error("Error parsing snapshotUrls", e);
             }
         } else if(incident.imageUrl) {
             // Fallback to single image
             if (incident.imageUrl && !incident.imageUrl.includes('null')) {
                 const img = document.createElement('img');
                 img.src = API_BASE + incident.imageUrl;
                 img.style.maxWidth = '200px';
                 img.style.border = '1px solid #ccc';
                 reportSnapshots.appendChild(img);
             }
         }
    } else {
        aiReportContainer.classList.add('hidden');
    }

    // 3. Populate Video/Snapshots
    const processedVideo = document.getElementById('processed-video');
    
    // NEW: Show videoUrl if available
    if (incident.videoUrl) {
        processedVideo.src = API_BASE + incident.videoUrl;
        processedVideo.style.display = 'block';
    } else if (incident.videoUrl) { // Legacy fallback
        processedVideo.src = API_BASE + incident.videoUrl;
        processedVideo.style.display = 'block';
    } else {
        processedVideo.style.display = 'none';
    }

    const gallery = document.getElementById('snapshot-gallery');
    gallery.innerHTML = '';
    
    // NEW: Display all snapshots from snapshotUrls
    if (incident.snapshotUrls) {
        try {
            const snapshotArray = JSON.parse(incident.snapshotUrls);
            const labels = ["Before", "During", "After"];
            
            snapshotArray.forEach((url, idx) => {
                if (!url || url.includes('null')) return; // Check for valid URL
                const wrap = document.createElement('div');
                wrap.style.textAlign = 'center';
                const label = (idx < 3) ? labels[idx] : `Snapshot ${idx+1}`;
                
                wrap.innerHTML = `<img src="${API_BASE + url}" style="width:160px; height:auto; border-radius:4px; border:1px solid #555; cursor: pointer;" onclick="openLightbox(this.src)">
                                 <div style="font-size:0.8em; color:#aaa; margin-top:2px;">${label}</div>`;
                gallery.appendChild(wrap);
            });
        } catch (e) {
            console.error("Error parsing snapshotUrls", e);
            // Fallback to single image
            if (incident.imageUrl) {
                const wrap = document.createElement('div');
                wrap.innerHTML = `<img src="${API_BASE + incident.imageUrl}" style="width:160px; height:auto; border-radius:4px; border:1px solid #555; cursor: pointer;" onclick="openLightbox(this.src)">`;
                gallery.appendChild(wrap);
            }
        }
    } else if (incident.imageUrl && !incident.imageUrl.includes('null')) {
        // Fallback to single legacy image
        const wrap = document.createElement('div');
        wrap.innerHTML = `<img src="${API_BASE + incident.imageUrl}" style="width:160px; height:auto; border-radius:4px; border:1px solid #555; cursor: pointer;" onclick="openLightbox(this.src)">`;
        gallery.appendChild(wrap);
    }
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
            
            // Sort by timestamp descending (newest first)
            allIncidents = data.sort((a, b) => {
                return new Date(b.timestamp) - new Date(a.timestamp);
            });
            
            // Count stats
            incidentCount = allIncidents.length;
            todayCount = allIncidents.filter(inc => isToday(inc.timestamp)).length;
            countTotalVal.innerText = incidentCount;
            countTodayVal.innerText = todayCount;
            
            // Display only first 5 items
            displayedCount = 0;
            incidentList.innerHTML = ''; // Clear existing
            loadMoreIncidents();
            
        } else {
             console.error("Failed to load history: HTTP", res.status);
        }
    } catch (e) {
        console.error("Failed to load history", e);
    }
}

function loadMoreIncidents() {
    const endIndex = Math.min(displayedCount + ITEMS_PER_PAGE, allIncidents.length);
    
    for (let i = displayedCount; i < endIndex; i++) {
        addToFeed(allIncidents[i], false);
    }
    
    displayedCount = endIndex;
    
    // Show/hide Load More button
    updateLoadMoreButton();
}

function updateLoadMoreButton() {
    let loadMoreBtn = document.getElementById('load-more-btn');
    
    if (displayedCount < allIncidents.length) {
        if (!loadMoreBtn) {
            loadMoreBtn = document.createElement('button');
            loadMoreBtn.id = 'load-more-btn';
            loadMoreBtn.className = 'btn-primary';
            loadMoreBtn.style.cssText = 'width: 100%; margin-top: 15px; padding: 12px;';
            loadMoreBtn.textContent = `Xem thêm (${allIncidents.length - displayedCount} còn lại)`;
            loadMoreBtn.onclick = loadMoreIncidents;
            incidentList.parentElement.appendChild(loadMoreBtn);
        } else {
            loadMoreBtn.textContent = `Xem thêm (${allIncidents.length - displayedCount} còn lại)`;
        }
    } else if (loadMoreBtn) {
        loadMoreBtn.remove();
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
        
        // Show controls
        modelDiv.classList.remove('hidden');
        optionsDiv.classList.remove('hidden');
        optionsDiv.style.display = 'flex';

        statusDiv.classList.add('hidden');
        resultDiv.classList.add('hidden');
        stopWebRTC();
    }
}

// Persist model selection on change
document.getElementById('model-select').addEventListener('change', saveState);


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
    document.getElementById('ai-report-container').classList.add('hidden');
    document.getElementById('create-report-section').classList.add('hidden');
        
    // --- UPLOAD TO JAVA (SPRING BOOT) ---
    const formData = new FormData();
    const modelType = document.getElementById('model-select').value;
    const confThreshold = document.getElementById('conf-threshold').value;
    const autoReport = document.getElementById('auto-report').checked;
    
    formData.append('file', file);
    formData.append('realtime', isRealtime);
    formData.append('modelType', modelType);
    formData.append('confidenceThreshold', confThreshold);
    formData.append('autoReport', autoReport); // NEW: Send auto-report preference

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
                // Hide options
                optionsDiv.classList.add('hidden');
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
            
            // Use processed video (with annotations)
            processedVideo.src = API_BASE + linkData.downloadUrl;
            
            // Show "Create Report" button instead of immediate result
            const createReportSection = document.getElementById('create-report-section');
            createReportSection.classList.remove('hidden');
            
            // Store data for report generation
            window.currentTaskData = linkData;
            window.currentTaskId = taskId;

            // Render Snapshots immediately
            const gallery = document.getElementById('snapshot-gallery');
            const reportSnapshots = document.getElementById('report-snapshots');
            gallery.innerHTML = ''; 
            reportSnapshots.innerHTML = '';
            
            if (linkData.snapshots && linkData.snapshots.length > 0) {
                const labels = ["Before", "During", "After"];
                linkData.snapshots.forEach((url, idx) => {
                    if (!url || url.includes('null')) return;
                    
                    const wrap = document.createElement('div');
                    wrap.style.textAlign = 'center';
                    
                    const label = (idx < 3) ? labels[idx] : `Snapshot ${idx+1}`;
                    
                    // Main Gallery
                    wrap.innerHTML = `
                        <img src="${API_BASE + url}" style="width:160px; height:auto; border-radius:4px; border:1px solid #555; cursor: pointer;" onclick="openLightbox(this.src)">
                        <div style="font-size:0.8em; color:#aaa; margin-top:2px;">${label}</div>
                    `;
                    gallery.appendChild(wrap);
                    
                    // Clone for Report PDF view
                    const clone = document.createElement('img');
                    clone.src = API_BASE + url;
                    clone.style.height = '150px';
                    clone.style.margin = '5px';
                    reportSnapshots.appendChild(clone);
                });
            }
            
            // Hide pre-existing report container until generated
            aiReportContainer.classList.add('hidden');

            // --- NEW: AUTO DISPLAY REPORT IF AVAILABLE ---
            // If the backend has already generated the report (because autoReport=true)
            if (linkData.aiReport) {
                console.log("Auto-displaying generated report...");
                
                // Hide "Create Report" button since it's done
                createReportSection.classList.add('hidden');
                
                // Populate and show report
                const reportContent = linkData.aiReport;
                const header = `Report Date: ${new Date().toLocaleString()}\n\n`;
                
                const cleanedContent = cleanMarkdown(reportContent);
                const summary = extractSummary(cleanedContent);
                
                const reportSummary = document.getElementById('ai-report-summary');
                const toggleBtn = document.getElementById('toggle-report-btn');
                const aiReportText = document.getElementById('ai-report-text');
                const aiReportContainer = document.getElementById('ai-report-container');
                
                reportSummary.textContent = summary;
                aiReportText.textContent = header + cleanedContent;
                
                aiReportText.classList.add('hidden');
                reportSummary.classList.remove('hidden');
                
                toggleBtn.textContent = 'Xem chi tiết báo cáo ▼';
                toggleBtn.style.display = cleanedContent.length > summary.length + 100 ? 'block' : 'none';
                
                aiReportContainer.classList.remove('hidden');
            }
            
        } else if (status.status === 'FAILED') {
            statusDiv.classList.add('hidden');
            // ... (rest of error handling)
            const uploadInputSection = document.getElementById('upload-input-section');
            if(uploadInputSection) uploadInputSection.classList.remove('hidden');
            if(optionsDiv) optionsDiv.classList.remove('hidden');
            alert("Analysis Failed: " + status.message);
        } else {
            // Keep polling
            setTimeout(() => pollStatus(taskId), 1000);
        }

    } catch (e) {
        console.error("Poll Error:", e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadTheme(); // Load saved theme preference
    connect(); // Restore Connection
    loadHistory();
    restoreState(); // Restore Model Selection
    const lastTaskId = sessionStorage.getItem('lastTaskId');
    if (lastTaskId) { pollStatus(lastTaskId); }
});

// --- NEW REPORT FUNCTIONS ---

// Helper function to clean markdown formatting
function cleanMarkdown(text) {
    if (!text) return '';
    
    // Remove markdown bold ** symbols
    let cleaned = text.replace(/\*\*(.+?)\*\*/g, '$1');
    
    // Remove markdown italic * symbols (single asterisk)
    cleaned = cleaned.replace(/(?<!\*)\*(?!\*)(.+?)\*(?!\*)/g, '$1');
    
    // Clean up extra newlines
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
    
    return cleaned;
}

// Helper function to extract summary from report
function extractSummary(text, maxLength = 300) {
    if (!text) return '';
    
    // Try to extract the content after "1. Tóm tắt" or similar numbered sections
    // Match pattern: "1. Tóm tắt..." followed by content until next numbered section or end
    const summaryMatch = text.match(/1\.?\s*(?:Tóm tắt|Summary)[^:]*:?\s*\n?\s*([^\n]+(?:\n(?!\d+\.)[^\n]+)*)/i);
    
    if (summaryMatch && summaryMatch[1]) {
        const summary = summaryMatch[1].trim();
        // Remove any markdown formatting
        const cleaned = summary.replace(/\*\*/g, '').replace(/\*/g, '');
        return cleaned.length > maxLength ? cleaned.substring(0, maxLength) + '...' : cleaned;
    }
    
    // Fallback: Try to find any text after first header/title
    const lines = text.split('\n').filter(l => l.trim());
    if (lines.length > 1) {
        // Skip header lines (usually in uppercase or with special markers)
        let startIdx = 0;
        while (startIdx < lines.length && (lines[startIdx].includes('===') || lines[startIdx].includes('BÁO CÁO') || lines[startIdx].length < 10)) {
            startIdx++;
        }
        if (startIdx < lines.length) {
            const content = lines.slice(startIdx, startIdx + 3).join(' ');
            return content.length > maxLength ? content.substring(0, maxLength) + '...' : content;
        }
    }
    
    // Final fallback
    const firstPara = text.split('\n\n')[0];
    return firstPara.length > maxLength ? firstPara.substring(0, maxLength) + '...' : firstPara;
}

async function generateAIReport() {
    const btn = document.getElementById('btn-create-report');
    const loading = document.getElementById('report-loading');
    const reportContainer = document.getElementById('ai-report-container');
    const reportText = document.getElementById('ai-report-text');
    const reportSummary = document.getElementById('ai-report-summary');
    const toggleBtn = document.getElementById('toggle-report-btn');
    
    // UI Loading State
    btn.parentElement.classList.add('hidden');
    loading.classList.remove('hidden');
    
    try {
        // If we don't have task data yet, fetch it from backend
        if (!window.currentTaskData || !window.currentTaskData.aiReport) {
            if (window.currentTaskId) {
                console.log("Fetching AI report from backend...");
                const linkRes = await fetch(`${API_BASE}/api/videos/result/${window.currentTaskId}`);
                if (linkRes.ok) {
                    window.currentTaskData = await linkRes.json();
                } else {
                    throw new Error("Failed to fetch report data");
                }
            }
        }
        
        // Small delay for UX
        await new Promise(resolve => setTimeout(resolve, 300));
        
        // If we don't have aiReport yet, request one from the server (on-demand)
        if (!window.currentTaskData || !window.currentTaskData.aiReport) {
            if (window.currentTaskId) {
                console.log("Requesting AI report generation on-demand...");
                
                // Call new API endpoint to generate report
                const genRes = await fetch(`${API_BASE}/api/videos/generate-report/${window.currentTaskId}`, {
                    method: 'POST'
                });
                
                if (genRes.ok) {
                    const genData = await genRes.json();
                    if (genData.success && genData.aiReport) {
                        if (!window.currentTaskData) window.currentTaskData = {};
                        window.currentTaskData.aiReport = genData.aiReport;
                    } else {
                        throw new Error(genData.error || "Failed to generate report");
                    }
                } else {
                    // Fallback: try getting existing result
                    const linkRes = await fetch(`${API_BASE}/api/videos/result/${window.currentTaskId}`);
                    if (linkRes.ok) {
                        window.currentTaskData = await linkRes.json();
                    } else {
                        throw new Error("Failed to fetch report data");
                    }
                }
            }
        }
        
        // Update UI after fetching/generating report
        loading.classList.add('hidden');
        reportContainer.classList.remove('hidden');
        
        if (window.currentTaskData && window.currentTaskData.aiReport) {
             const rawText = window.currentTaskData.aiReport;
             
             // Clean markdown formatting
             const cleanedText = cleanMarkdown(rawText);
             
             // Add date/time header
             const header = `Report Date: ${new Date().toLocaleString()}\n\n`;
             
             // Extract and display summary
             const summary = extractSummary(cleanedText);
             reportSummary.textContent = summary;
             
             // Store full report (hidden)
             reportText.textContent = header + cleanedText;
             
             // Show toggle button if report is long enough
             if (reportText.textContent.length > summary.length + 100) {
                 toggleBtn.style.display = 'block';
             } else {
                 toggleBtn.style.display = 'none';
             }
        } else {
             reportSummary.textContent = "No AI analysis available for this video.";
             toggleBtn.style.display = 'none';
        }
        
    } catch (error) {
        console.error("Error generating report:", error);
        loading.classList.add('hidden');
        reportContainer.classList.remove('hidden');
        reportSummary.textContent = "⚠️ Error loading AI report. Please try again.";
        toggleBtn.style.display = 'none';
    }
}

// Toggle between summary and full report
function toggleFullReport() {
    const reportText = document.getElementById('ai-report-text');
    const reportSummary = document.getElementById('ai-report-summary');
    const toggleBtn = document.getElementById('toggle-report-btn');
    
    if (reportText.classList.contains('hidden')) {
        // Show full report
        reportText.classList.remove('hidden');
        reportSummary.classList.add('hidden');
        toggleBtn.textContent = 'Thu gọn báo cáo ▲';
    } else {
        // Show summary only
        reportText.classList.add('hidden');
        reportSummary.classList.remove('hidden');
        toggleBtn.textContent = 'Xem chi tiết báo cáo ▼';
    }
}

function exportToPDF() {
    const reportContainer = document.getElementById('ai-report-container');
    const originalContent = document.body.innerHTML;
    
    // Simple Print Logic
    // We isolate the report container for printing
    const printContent = reportContainer.innerHTML;
    
    const printWindow = window.open('', '', 'height=600,width=800');
    printWindow.document.write('<html><head><title>Incident Report</title>');
    printWindow.document.write('<style>');
    printWindow.document.write('body { font-family: sans-serif; padding: 20px; color: #000; }');
    printWindow.document.write('img { max-width: 100%; height: auto; display: block; margin: 10px auto; }');
    printWindow.document.write('h2, h4 { color: #333; }');
    printWindow.document.write('p { line-height: 1.6; white-space: pre-wrap; }');
    printWindow.document.write('</style>');
    printWindow.document.write('</head><body>');
    printWindow.document.write(printContent);
    printWindow.document.write('</body></html>');
    
    printWindow.document.close();
    printWindow.focus();
    // setTimeout to allow images to load in new window?
    setTimeout(() => {
        printWindow.print();
        printWindow.close();
    }, 500);
}


function switchMode(mode) {
    const uploadInputSection = document.getElementById('upload-input-section');
    const optionsDiv = document.getElementById('analysis-options');
    const previewContainer = document.getElementById('video-preview-container');
    const resultDiv = document.getElementById('video-result');
    const liveSection = document.getElementById('live-stream-section');
    const uploadBtn = document.getElementById('mode-upload-btn');
    const liveBtn = document.getElementById('mode-live-btn');
    const analyzeBtn = document.getElementById('analyze-btn');
    const analyzeBtnIcon = document.getElementById('analyze-btn-icon');
    const analyzeBtnText = document.getElementById('analyze-btn-text');

    if (mode === 'live') {
        // Real-time Stream Mode
        currentMode = 'realtime';
        
        // Update button to Stream style
        analyzeBtn.className = 'action-btn stream-btn';
        analyzeBtnIcon.textContent = '▶️';
        analyzeBtnText.textContent = 'Start Stream';
        
        if(optionsDiv) optionsDiv.classList.remove('hidden');

        previewContainer.classList.add('hidden');
        resultDiv.classList.add('hidden');
        liveSection.classList.remove('hidden');
        
        // Update tab styling
        liveBtn.classList.add('active');
        uploadBtn.classList.remove('active');
        
    } else {
        // Batch Analysis Mode
        currentMode = 'batch';
        
        // Update button to Batch style
        analyzeBtn.className = 'action-btn batch-btn';
        analyzeBtnIcon.textContent = '⚡';
        analyzeBtnText.textContent = 'Start Analysis';
        
        stopWebRTC();
        uploadInputSection.classList.remove('hidden');

        if(optionsDiv && document.getElementById('video-input').files.length > 0) {
             optionsDiv.classList.remove('hidden');
        }
        liveSection.classList.add('hidden');
        
        // Update tab styling
        uploadBtn.classList.add('active');
        liveBtn.classList.remove('active');
        
        if (document.getElementById('video-input').files.length > 0) {
             previewContainer.classList.remove('hidden');
        }
    }
}

// New unified function that uses current mode
function startCurrentModeAnalysis() {
    const isRealtime = (currentMode === 'realtime');
    startAnalysis(isRealtime);
}
// --- Lightbox Functions ---
function openLightbox(imgSrc) {
    const modal = document.getElementById('lightbox-modal');
    const modalImg = document.getElementById('lightbox-img');
    modal.classList.add('show');
    modalImg.src = imgSrc;
    
    // Close on click outside
    modal.onclick = function(e) {
        if(e.target === modal) {
            closeLightbox();
        }
    }
}

function closeLightbox() {
    const modal = document.getElementById('lightbox-modal');
    modal.classList.remove('show');
}

// Close on Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === "Escape") {
        closeLightbox();
    }
});
