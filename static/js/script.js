/**
 * Traffic Density Analyzer - Main JavaScript
 * Handles interactive functionality for the application
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    if (tooltipTriggerList.length) {
        [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    }

    // Handle automatic alert dismissal
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const closeButton = alert.querySelector('.btn-close');
            if (closeButton) {
                closeButton.click();
            }
        }, 5000); // Auto-dismiss after 5 seconds
    });

    // Handle file upload form
    const uploadForm = document.getElementById('upload-form');
    if (uploadForm) {
        const fileInput = document.getElementById('file-input');
        const uploadBtn = document.getElementById('upload-btn');
        const progressBar = document.querySelector('.progress');
        const progressInner = document.querySelector('.progress-bar');

        // Update choose file button text when file is selected
        fileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                const fileName = this.files[0].name;
                uploadBtn.innerHTML = `<i class="fas fa-upload me-2"></i>Analyze ${fileName}`;
                validateFileInput(this);
            }
        });

        // Handle form submission
        uploadForm.addEventListener('submit', function(e) {
            if (!fileInput.files.length) {
                e.preventDefault();
                showMessage('Please select a file to upload.', 'warning');
                return;
            }

            if (!validateFileInput(fileInput)) {
                e.preventDefault();
                return;
            }

            // Show progress
            progressBar.style.display = 'block';

            // Disable button and show loading state
            showLoading(uploadBtn, 'Processing...');

            // Simulate progress (in a real app, this would be actual upload progress)
            let progress = 0;
            const progressInterval = setInterval(function() {
                progress += 5;
                if (progress <= 90) {
                    progressInner.style.width = progress + '%';
                }

                if (progress >= 90) {
                    clearInterval(progressInterval);
                }
            }, 300);
        });
    }

    // Handle video controls on results page
    const trafficVideo = document.getElementById('traffic-video');
    
    if (trafficVideo) {
        const playPauseBtn = document.getElementById('play-pause');
        const toggleAnnotationsBtn = document.getElementById('toggle-annotations');
        const downloadBtn = document.getElementById('download-btn');
        
        if (playPauseBtn) {
            playPauseBtn.addEventListener('click', function() {
                if (trafficVideo.paused) {
                    trafficVideo.play();
                    this.innerHTML = '<i class="fas fa-pause"></i>';
                } else {
                    trafficVideo.pause();
                    this.innerHTML = '<i class="fas fa-play"></i>';
                }
            });
        }

        // Update play/pause button on video events
        trafficVideo.addEventListener('play', () => {
            if (playPauseBtn) {
                playPauseBtn.innerHTML = '<i class="fas fa-pause"></i>';
            }
        });

        trafficVideo.addEventListener('pause', () => {
            if (playPauseBtn) {
                playPauseBtn.innerHTML = '<i class="fas fa-play"></i>';
            }
        });

        trafficVideo.addEventListener('ended', () => {
            if (playPauseBtn) {
                playPauseBtn.innerHTML = '<i class="fas fa-play"></i>';
            }
        });

        // Toggle detection boxes
        if (toggleAnnotationsBtn) {
            toggleAnnotationsBtn.addEventListener('click', function() {
                const overlay = document.getElementById('detectionOverlay');
                if (overlay) {
                    overlay.style.display = overlay.style.display === 'none' ? 'block' : 'none';
                }
            });
        }
    }

    // Vehicle distribution chart setup (if needed)
    const distributionChart = document.getElementById('distributionChart');
    if (distributionChart) {
        const distributionCtx = distributionChart.getContext('2d');
        const distributionData = {
            labels: ['Cars', 'Trucks', 'Motorcycles', 'Buses'],
            datasets: [{
                data: [65, 15, 12, 8],
                backgroundColor: ['#0d6efd', '#dc3545', '#ffc107', '#198754']
            }]
        };
        new Chart(distributionCtx, {
            type: 'doughnut',
            data: distributionData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }

    const downloadBtn = document.getElementById('download-btn'); // Added download button
    if (downloadBtn){
        downloadBtn.addEventListener('click', function(){
            // Placeholder for download functionality.  In a real application, this would trigger a download of the processed video.
            alert('Download initiated (placeholder)');
        });
    }


});

/**
 * Shows a loading indicator in the specified button
 * @param {HTMLElement} button - The button element to show loading state
 * @param {string} loadingText - Text to display during loading
 */
function showLoading(button, loadingText = 'Processing...') {
    button.disabled = true;
    button.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${loadingText}`;
}

/**
 * Resets the button to its original state
 * @param {HTMLElement} button - The button element
 * @param {string} originalText - Original button text
 */
function resetButton(button, originalText) {
    button.disabled = false;
    button.innerHTML = originalText;
}

/**
 * Validates file input to ensure it's an allowed file type and size
 * @param {HTMLInputElement} fileInput - The file input element
 * @returns {boolean} Whether the file is valid
 */
function validateFileInput(fileInput) {
    const allowedTypes = ['image/jpeg', 'image/png', 'video/mp4', 'video/avi', 'video/quicktime'];
    const maxSizeMB = 200;

    if (!fileInput.files.length) {
        return false;
    }

    const file = fileInput.files[0];

    // Check file type
    if (!allowedTypes.includes(file.type)) {
        showMessage('Invalid file type. Please upload an image (JPG, PNG) or video (MP4, AVI, MOV).', 'danger');
        fileInput.value = '';
        return false;
    }

    // Check file size (convert MB to bytes)
    const maxSizeBytes = maxSizeMB * 1024 * 1024;
    if (file.size > maxSizeBytes) {
        showMessage(`File is too large. Maximum size is ${maxSizeMB}MB.`, 'danger');
        fileInput.value = '';
        return false;
    }

    return true;
}

// Register Chart.js DataLabels if available
if (window.Chart && window.ChartDataLabels) {
    Chart.register(window.ChartDataLabels);
}

// Button ripple mouse position (for CSS ::after)
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-primary');
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    btn.style.setProperty('--x', `${e.clientX - rect.left}px`);
    btn.style.setProperty('--y', `${e.clientY - rect.top}px`);
});

// Prefers-reduced-motion: disable long animations if requested
const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if (prefersReduced) {
    document.documentElement.style.setProperty('--shadow', 'none');
}

// Extract dominant color from preview image to set accent
async function extractAccentFromImage(imgEl) {
    try {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const w = canvas.width = Math.min(64, imgEl.naturalWidth || 64);
        const h = canvas.height = Math.min(64, imgEl.naturalHeight || 64);
        ctx.drawImage(imgEl, 0, 0, w, h);
        const data = ctx.getImageData(0, 0, w, h).data;
        let r=0,g=0,b=0,count=0;
        for (let i=0; i<data.length; i+=4*8) { // sample every 8 pixels
            r += data[i]; g += data[i+1]; b += data[i+2]; count++;
        }
        r = Math.round(r/count); g = Math.round(g/count); b = Math.round(b/count);
        const accent = `rgb(${r}, ${g}, ${b})`;
        document.documentElement.style.setProperty('--accent', accent);
        localStorage.setItem('accentColor', accent);
    } catch (_) {}
}

/**
 * Shows a message to the user
 * @param {string} message - The message to display
 * @param {string} type - The alert type (success, danger, warning, info)
 */
function showMessage(message, type = 'info') {
    const alertContainer = document.querySelector('.alert-container');
    if (alertContainer) {
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show`;
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        alertContainer.appendChild(alert);

        // Auto dismiss after 5 seconds
        setTimeout(() => {
            alert.querySelector('.btn-close').click();
        }, 5000);
    } else {
        // Fallback to regular alert if container doesn't exist
        alert(message);
    }
}

function compareHistorical() {
    // Implement historical comparison
    alert('Comparing with historical data...');
}