const API_BASE = window.location.origin;
let currentUsername = '';
let loadedPosts = [];
let totalPostCount = 0;
let postsPerLoad = 12;

/**
 * Normalizes user input into a plain Instagram username.
 * @param {string} input Raw username or profile URL entered by the user.
 * @returns {string} Extracted username without reserved path segments.
 */
function extractUsername(input) {
    input = input.trim();
    
    // Remove @ if present at the start
    if (input.startsWith('@')) {
        return input.substring(1);
    }
    
    // Check if it's an Instagram URL
    const urlPatterns = [
        /(?:https?:\/\/)?(?:www\.)?instagram\.com\/([a-zA-Z0-9._]+)\/?(?:\?.*)?$/,
        /(?:https?:\/\/)?(?:www\.)?instagr\.am\/([a-zA-Z0-9._]+)\/?(?:\?.*)?$/
    ];
    
    for (const pattern of urlPatterns) {
        const match = input.match(pattern);
        if (match && match[1]) {
            // Exclude reserved paths
            const reserved = ['p', 'reel', 'reels', 'stories', 'explore', 'accounts', 'direct', 'tv'];
            if (!reserved.includes(match[1].toLowerCase())) {
                return match[1];
            }
        }
    }
    
    // Return as-is if no URL pattern matched (assume it's a username)
    return input;
}

// Zoom state
let currentZoom = 1;
let translateX = 0;
let translateY = 0;
let isDragging = false;
let startX = 0;
let startY = 0;

// Fullscreen modal functions
/**
 * Opens the fullscreen modal with the provided asset and resets zoom state.
 * @param {string} src Source URL for the image to display.
 * @returns {void}
 */
function openFullscreen(src) {
    const modal = document.getElementById('fullscreenModal');
    const img = document.getElementById('fullscreenImage');
    img.src = src;
    resetZoom();
    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
}

/**
 * Closes the fullscreen modal and restores scrolling.
 * @returns {void}
 */
function closeFullscreen() {
    const modal = document.getElementById('fullscreenModal');
    modal.classList.remove('show');
    document.body.style.overflow = '';
    resetZoom();
}

/**
 * Applies the current zoom and pan state to the fullscreen image.
 * @returns {void}
 */
function updateTransform() {
    const img = document.getElementById('fullscreenImage');
    img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${currentZoom})`;
    document.getElementById('zoomLevel').textContent = Math.round(currentZoom * 100) + '%';
}

/**
 * Increases the zoom level for the fullscreen image.
 * @returns {void}
 */
function zoomIn() {
    if (currentZoom < 5) {
        currentZoom = Math.min(5, currentZoom + 0.25);
        updateTransform();
    }
}

/**
 * Decreases the zoom level while constraining pan offsets.
 * @returns {void}
 */
function zoomOut() {
    if (currentZoom > 0.25) {
        currentZoom = Math.max(0.25, currentZoom - 0.25);
        // Constrain pan when zooming out
        if (currentZoom <= 1) {
            translateX = 0;
            translateY = 0;
        }
        updateTransform();
    }
}

/**
 * Resets zoom and pan to their default values.
 * @returns {void}
 */
function resetZoom() {
    currentZoom = 1;
    translateX = 0;
    translateY = 0;
    updateTransform();
}

// Initialize event listeners when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Mouse wheel zoom
    document.getElementById('fullscreenModal').addEventListener('wheel', (e) => {
        e.preventDefault();
        if (e.deltaY < 0) {
            zoomIn();
        } else {
            zoomOut();
        }
    }, { passive: false });

    // Drag to pan
    const imageContainer = document.getElementById('imageContainer');
    
    imageContainer.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'IMG' && currentZoom > 1) {
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
            imageContainer.classList.add('dragging');
            e.preventDefault();
        }
    });

    document.addEventListener('mousemove', (e) => {
        if (isDragging) {
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            updateTransform();
        }
    });

    document.addEventListener('mouseup', () => {
        isDragging = false;
        imageContainer.classList.remove('dragging');
    });

    // Double-click to reset
    imageContainer.addEventListener('dblclick', (e) => {
        if (e.target.tagName === 'IMG') {
            resetZoom();
        }
    });

    // Click outside image to close
    imageContainer.addEventListener('click', (e) => {
        if (e.target === imageContainer && !isDragging) {
            closeFullscreen();
        }
    });

    // Close modal with Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeFullscreen();
        }
        // Keyboard shortcuts for zoom
        const modal = document.getElementById('fullscreenModal');
        if (modal.classList.contains('show')) {
            if (e.key === '+' || e.key === '=') {
                zoomIn();
            } else if (e.key === '-') {
                zoomOut();
            } else if (e.key === '0') {
                resetZoom();
            }
        }
    });

    // Get Profile Info
    document.getElementById('getProfileBtn').addEventListener('click', getProfile);
    document.getElementById('username').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') getProfile();
    });
    
    // Auto-extract username when pasting
    document.getElementById('username').addEventListener('paste', (e) => {
        setTimeout(() => {
            const input = document.getElementById('username');
            const extracted = extractUsername(input.value);
            if (extracted !== input.value) {
                input.value = extracted;
                showStatus(`Username extracted: @${extracted}`, 'info');
            }
        }, 0);
    });
});

/**
 * Fetches profile metadata and updates the UI for the current username.
 * @returns {Promise<void>}
 */
async function getProfile() {
    const rawInput = document.getElementById('username').value;
    const username = extractUsername(rawInput);
    
    if (!username) {
        showStatus('Please enter a username or Instagram profile URL', 'warning');
        return;
    }
    
    // Update input field with extracted username
    document.getElementById('username').value = username;

    currentUsername = username;
    const btn = document.getElementById('getProfileBtn');
    const spinner = document.getElementById('profileSpinner');
    const icon = document.getElementById('searchIcon');
    
    btn.disabled = true;
    spinner.classList.add('show');
    icon.style.display = 'none';

    try {
        const response = await fetch(`${API_BASE}/profile/${username}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || data.error || 'Failed to fetch profile');
        }

        // Update profile card
        document.getElementById('profilePic').src = `${API_BASE}/download/profile-pic/${data.username}?url_only=false`;
        document.getElementById('profileUsername').textContent = '@' + data.username;
        document.getElementById('profileFullname').textContent = data.full_name || '';
        document.getElementById('profileBio').textContent = data.biography || 'No bio';  // pre-wrap CSS preserves line breaks
        document.getElementById('followers').textContent = formatNumber(data.followers);
        document.getElementById('following').textContent = formatNumber(data.following);
        document.getElementById('postCount').textContent = formatNumber(data.post_count);
        
        document.getElementById('verifiedBadge').className = data.is_verified ? 'stat-badge badge-visible' : 'stat-badge badge-hidden';
        document.getElementById('privateBadge').className = data.is_private ? 'stat-badge badge-visible' : 'stat-badge badge-hidden';

        // Show cards
        document.getElementById('profileCard').classList.add('show');
        document.getElementById('downloadOptions').classList.add('show');
        
        // Store total post count; do NOT auto-fetch posts to avoid rate limits
        totalPostCount = data.post_count;
        document.getElementById('totalPostsCount').textContent = data.post_count;
        
        // Prepare posts section state
        loadedPosts = [];
        document.getElementById('postsGrid').innerHTML = '';
        document.getElementById('loadedPostsCount').textContent = '0';
        document.getElementById('loadMoreBtn').style.display = 'none';
        document.getElementById('fetchPostsBtn').disabled = false;
        document.getElementById('fetchPostsSpinner').classList.add('d-none');
        document.getElementById('fetchPostsText').textContent = 'Fetch Posts';
        
        if (!data.is_private && data.post_count > 0) {
            document.getElementById('postsSection').classList.add('show');
        } else {
            document.getElementById('postsSection').classList.remove('show');
        }
        
        showStatus('Profile loaded successfully!', 'success');

    } catch (error) {
        showStatus(error.message, 'danger');
        document.getElementById('profileCard').classList.remove('show');
        document.getElementById('downloadOptions').classList.remove('show');
        document.getElementById('postsSection').classList.remove('show');
    } finally {
        btn.disabled = false;
        spinner.classList.remove('show');
        icon.style.display = 'inline';
    }
}

// Load posts from API
/**
 * Retrieves and renders a batch of posts for the current profile.
 * @param {boolean} [reset=false] Flag indicating whether to reset existing state.
 * @returns {Promise<void>}
 */
async function loadPosts(reset = false) {
    const btn = document.getElementById('fetchPostsBtn');
    const spinner = document.getElementById('fetchPostsSpinner');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const btnText = document.getElementById('fetchPostsText');

    if (reset) {
        loadedPosts = [];
        document.getElementById('postsGrid').innerHTML = '';
        document.getElementById('loadedPostsCount').textContent = '0';
        loadMoreBtn.classList.add('hidden');
    }

    btn.disabled = true;
    spinner.classList.remove('d-none');
    btnText.textContent = 'Loading...';

    try {
        const response = await fetch(`${API_BASE}/profile/${currentUsername}/posts?max_posts=${postsPerLoad}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load posts');
        }
        
        loadedPosts = data.posts;
        renderPosts(data.posts);
        document.getElementById('loadedPostsCount').textContent = loadedPosts.length;
        
        // Show/hide load more button (API currently returns max 50 at once)
        if (loadedPosts.length < totalPostCount && loadedPosts.length < 50) {
            loadMoreBtn.classList.remove('hidden');
        } else {
            loadMoreBtn.classList.add('hidden');
        }
        
    } catch (error) {
        showStatus(error.message, 'danger');
    } finally {
        spinner.classList.add('d-none');
        btn.disabled = false;
        btnText.textContent = 'Fetch Posts';
    }
}

/**
 * Loads additional posts using an increased max_posts query parameter.
 * @returns {Promise<void>}
 */
async function loadMorePosts() {
    const btn = document.getElementById('loadMoreBtn');
    const spinner = document.getElementById('loadMoreSpinner');
    
    btn.disabled = true;
    spinner.classList.remove('d-none');
    
    try {
        const newMax = Math.min(loadedPosts.length + postsPerLoad, 50);
        const response = await fetch(`${API_BASE}/profile/${currentUsername}/posts?max_posts=${newMax}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to load more posts');
        }
        
        // Get only new posts
        const newPosts = data.posts.slice(loadedPosts.length);
        loadedPosts = data.posts;
        renderPosts(newPosts, true);
        document.getElementById('loadedPostsCount').textContent = loadedPosts.length;
        
        // Hide button if we've loaded all or reached max
        if (loadedPosts.length >= totalPostCount || loadedPosts.length >= 50) {
            btn.classList.add('hidden');
        }
        
    } catch (error) {
        showStatus(error.message, 'danger');
    } finally {
        btn.disabled = false;
        spinner.classList.add('d-none');
    }
}

/**
 * Builds the proxied thumbnail URL for a given media resource.
 * @param {string} url Original media URL.
 * @returns {string} Proxied thumbnail endpoint.
 */
function getThumbnailSrc(url) {
    return `${API_BASE}/proxy/thumbnail?url=${encodeURIComponent(url)}`;
}

/**
 * Renders post tiles onto the grid container.
 * @param {Array<object>} posts Collection of post metadata objects.
 * @param {boolean} [append=false] Whether to append instead of replacing content.
 * @returns {void}
 */
function renderPosts(posts, append = false) {
    const grid = document.getElementById('postsGrid');
    if (!append) {
        grid.innerHTML = '';
    }
    
    posts.forEach((post, index) => {
        const postEl = document.createElement('div');
        postEl.className = 'post-item';
        postEl.setAttribute('role', 'listitem');
        postEl.innerHTML = `
            <img src="${getThumbnailSrc(post.thumbnail_url)}" alt="Instagram post ${index + 1} - ${post.is_video ? 'Video' : 'Photo'} with ${formatNumber(post.likes)} likes" loading="lazy" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%232d2d2d%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2250%22 text-anchor=%22middle%22 dy=%22.3em%22 fill=%22%23666%22 font-size=%2212%22>No image</text></svg>'">
            ${post.is_video ? '<span class="post-type-badge" aria-label="Video post"><i class="bi bi-play-circle-fill" aria-hidden="true"></i></span>' : ''}
            <div class="post-overlay">
                <div class="post-stats" aria-label="Post statistics">
                    <span><i class="bi bi-heart-fill" aria-hidden="true"></i> ${formatNumber(post.likes)}</span>
                    <span><i class="bi bi-chat-fill" aria-hidden="true"></i> ${formatNumber(post.comments)}</span>
                </div>
                <button class="post-download-btn" onclick="event.stopPropagation(); downloadSinglePost('${post.shortcode}', this)" aria-label="Download this post">
                    <i class="bi bi-download" aria-hidden="true"></i> Download
                </button>
            </div>
        `;
        
        // Click to open in new tab
        postEl.addEventListener('click', () => {
            window.open(post.post_url, '_blank');
        });
        
        // Click on image to view fullscreen
        const img = postEl.querySelector('img');
        img.addEventListener('click', (e) => {
            e.stopPropagation();
            openFullscreen(getThumbnailSrc(post.thumbnail_url));
        });
        
        grid.appendChild(postEl);
    });
}

/**
 * Downloads a single post asset by shortcode and updates button state.
 * @param {string} shortcode Instagram shortcode or URL.
 * @param {HTMLButtonElement} [btn] Button triggering the download for spinner state.
 * @returns {Promise<void>}
 */
async function downloadSinglePost(shortcode, btn) {
    const url = `${API_BASE}/download/post?url=${encodeURIComponent(shortcode)}`;
    const originalHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Preparing...';
    }
    try {
        await downloadFile(url, null, `${shortcode}`);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHtml || '<i class="bi bi-download"></i> Download';
        }
    }
}

// Download functions
/**
 * Initiates a full account download based on current username and options.
 * @returns {Promise<void>}
 */
async function downloadAll() {
    const maxPosts = document.getElementById('maxPostsAll').value;
    let url = `${API_BASE}/download/all/${currentUsername}`;
    if (maxPosts) url += `?max_posts=${maxPosts}`;
    await downloadFile(url, 'spinnerAll', `${currentUsername}.zip`);
}

/**
 * Downloads post media for the active profile.
 * @returns {Promise<void>}
 */
async function downloadPosts() {
    const maxPosts = document.getElementById('maxPostsPosts').value;
    let url = `${API_BASE}/download/posts/${currentUsername}`;
    if (maxPosts) url += `?max_posts=${maxPosts}`;
    await downloadFile(url, 'spinnerPosts', `${currentUsername}_posts.zip`);
}

/**
 * Downloads or copies the profile picture URL based on user selection.
 * @returns {Promise<void>}
 */
async function downloadProfilePic() {
    const urlOnly = document.getElementById('urlOnly').checked;
    const url = `${API_BASE}/download/profile-pic/${currentUsername}?url_only=${urlOnly}`;
    
    if (urlOnly) {
        const spinner = document.getElementById('spinnerPic');
        spinner.classList.remove('d-none');
        
        try {
            const response = await fetch(url);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || 'Failed to get profile picture URL');
            }
            
            // Copy URL to clipboard
            await navigator.clipboard.writeText(data.profile_pic_url);
            showStatus('Profile picture URL copied to clipboard!', 'success');
            
        } catch (error) {
            showStatus(error.message, 'danger');
        } finally {
            spinner.classList.add('d-none');
        }
    } else {
        await downloadFile(url, 'spinnerPic', `${currentUsername}_profile_pic.jpg`);
    }
}

/**
 * Downloads media using a direct Instagram post link.
 * @returns {Promise<void>}
 */
async function downloadByLink() {
    const postUrl = document.getElementById('postUrl').value.trim();
    if (!postUrl) {
        showStatus('Please enter a post URL or shortcode', 'warning');
        return;
    }

    const url = `${API_BASE}/download/post?url=${encodeURIComponent(postUrl)}`;
    await downloadFile(url, 'spinnerLink', 'instagram_post');
}

/**
 * Handles the fetch and client-side download flow for binary responses.
 * @param {string} url API endpoint to call for the download.
 * @param {string} [spinnerId] Optional spinner element ID.
 * @param {string} defaultFilename Fallback filename when headers are absent.
 * @returns {Promise<void>}
 */
async function downloadFile(url, spinnerId, defaultFilename) {
    const spinner = spinnerId ? document.getElementById(spinnerId) : null;
    if (spinner) spinner.classList.remove('d-none');
    showStatus('Downloading... This may take a while for large accounts.', 'info');

    try {
        const response = await fetch(url);
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || data.error || 'Download failed');
        }

        // Get filename from Content-Disposition header or use default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = defaultFilename;
        if (contentDisposition) {
            const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
            if (match) filename = match[1];
        }

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(downloadUrl);
        a.remove();

        showStatus('Download completed!', 'success');

    } catch (error) {
        showStatus(error.message, 'danger');
    } finally {
        if (spinner) spinner.classList.add('d-none');
    }
}

/**
 * Displays a status alert message for user feedback.
 * @param {string} message Text content for the alert.
 * @param {'success'|'danger'|'warning'|'info'} type Bootstrap alert variant.
 * @returns {void}
 */
function showStatus(message, type) {
    const container = document.getElementById('statusContainer');
    const icons = {
        success: 'check-circle',
        danger: 'exclamation-triangle',
        warning: 'exclamation-circle',
        info: 'info-circle'
    };
    
    container.innerHTML = `
        <div class="alert alert-${type} alert-custom alert-dismissible fade show" role="alert">
            <i class="bi bi-${icons[type]} me-2"></i>${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;

    // Auto-dismiss success messages
    if (type === 'success') {
        setTimeout(() => {
            const alert = container.querySelector('.alert');
            if (alert) alert.remove();
        }, 5000);
    }
}

/**
 * Formats large integers into shorthand notation (e.g., 1.2K).
 * @param {number} num Raw numeric value to format.
 * @returns {string} Shorthand string representation.
 */
function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}
