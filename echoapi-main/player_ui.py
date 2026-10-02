"""
🎵 EchoAPI Interactive Web Player
Renders a modern, responsive, glassmorphic audio/video player interface.
Features:
- Vinyl record sliding & spinning animation (synced with play/pause)
- Interactive cursor-following glassmorphic tooltip (desktop)
- Custom interactive audio controls with progress scrubber and volume
- Multi-layer gaussian blur ambient glow background
- Tactile glass buttons with ripple and copy-to-clipboard toast
"""

def render_player_html(
    video_id: str,
    title: str,
    artist: str,
    thumbnail: str,
    stream_url: str,
    video_url: str,
    duration_str: str = "3:30",
    method: str = "meta_backend"
) -> str:
    escaped_title = title.replace('"', '&quot;').replace("'", "&#39;")
    escaped_artist = artist.replace('"', '&quot;').replace("'", "&#39;")
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title} | EchoAPI Web Player</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        
        @keyframes pulseGlow {{
            0%, 100% {{ transform: scale(1); opacity: 0.3; }}
            50% {{ transform: scale(1.1); opacity: 0.45; }}
        }}

        @keyframes badgePulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.85); }}
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #060810;
            color: #f8fafc;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 32px 16px;
            overflow-x: hidden;
            position: relative;
        }}

        /* Gaussian Blur Ambient Background Glows */
        .bg-glow {{
            position: fixed;
            width: 550px;
            height: 550px;
            border-radius: 50%;
            filter: blur(140px);
            pointer-events: none;
            z-index: 0;
            animation: pulseGlow 10s infinite ease-in-out;
        }}
        .glow-1 {{
            top: -150px;
            left: -150px;
            background: radial-gradient(circle, #6366f1 0%, #4338ca 70%);
        }}
        .glow-2 {{
            bottom: -150px;
            right: -150px;
            background: radial-gradient(circle, #ec4899 0%, #8b5cf6 70%);
            animation-delay: -5s;
        }}
        .glow-3 {{
            top: 40%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 350px;
            height: 350px;
            background: radial-gradient(circle, #06b6d4 0%, transparent 70%);
            opacity: 0.15;
            filter: blur(100px);
        }}

        .player-wrapper {{
            position: relative;
            z-index: 10;
            width: 100%;
            max-width: 540px;
        }}

        /* Glass Panel Card */
        .glass-card {{
            background: rgba(13, 17, 30, 0.72);
            backdrop-filter: blur(36px);
            -webkit-backdrop-filter: blur(36px);
            border: 1px solid rgba(255, 255, 255, 0.09);
            border-radius: 32px;
            padding: 36px 32px;
            box-shadow: 
                0 30px 70px -15px rgba(0, 0, 0, 0.85),
                0 0 0 1px rgba(255, 255, 255, 0.05),
                inset 0 1px 1px rgba(255, 255, 255, 0.15);
            text-align: center;
            position: relative;
        }}

        /* Top Badges */
        .badge-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 28px;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 7px;
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            padding: 6px 14px;
            border-radius: 9999px;
            background: rgba(99, 102, 241, 0.14);
            color: #a5b4fc;
            border: 1px solid rgba(99, 102, 241, 0.28);
            box-shadow: 0 2px 10px rgba(99, 102, 241, 0.15);
        }}
        .badge-live {{
            background: rgba(16, 185, 129, 0.12);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.28);
            box-shadow: 0 2px 10px rgba(16, 185, 129, 0.15);
        }}
        .pulse-dot {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: currentColor;
            animation: badgePulse 1.8s infinite;
        }}

        /* ── Artwork & Vinyl Record Animation Container ── */
        .artwork-stage {{
            position: relative;
            width: 240px;
            height: 240px;
            margin: 0 auto 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        /* Vinyl Record */
        .vinyl-container {{
            position: absolute;
            top: 50%;
            left: 50%;
            width: 220px;
            height: 220px;
            pointer-events: none;
            z-index: 1;
            transform: translate(-50%, -50%) translateX(0);
            opacity: 0;
            transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.5s ease;
        }}

        /* When hovered or playing, vinyl smoothly slides out to the left */
        .artwork-stage:hover .vinyl-container,
        .artwork-stage.is-playing .vinyl-container {{
            opacity: 1;
            transform: translate(-50%, -50%) translateX(-85px);
        }}

        .vinyl-disc {{
            position: relative;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background-image: url('https://cdn.21st.dev/assets/mirror/b0/b0288bf1747bf704d2e3a44834fdcca14958fba916c9c6ca35136902babf739e.png');
            background-size: contain;
            background-position: center;
            background-repeat: no-repeat;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7);
            animation: spin 1.33s linear infinite;
            animation-play-state: paused;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        /* Center Label with Actual Song Image */
        .vinyl-center-label {{
            position: absolute;
            width: 78px;
            height: 78px;
            border-radius: 50%;
            overflow: hidden;
            box-shadow: 0 0 0 3px rgba(10, 10, 15, 0.95), inset 0 0 8px rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            background: #111;
        }}
        .vinyl-label-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            border-radius: 50%;
            display: block;
        }}
        .vinyl-center-hole {{
            position: absolute;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: #060810;
            border: 2px solid rgba(255, 255, 255, 0.2);
            box-shadow: 0 0 6px rgba(0, 0, 0, 0.9);
        }}

        /* Spin vinyl when music is actively playing */
        .artwork-stage.is-playing .vinyl-disc {{
            animation-play-state: running;
        }}

        /* Album Artwork Card */
        .album-art-card {{
            position: relative;
            z-index: 2;
            width: 240px;
            height: 240px;
            border-radius: 24px;
            overflow: hidden;
            box-shadow: 
                0 20px 40px -10px rgba(0, 0, 0, 0.8),
                0 0 35px rgba(99, 102, 241, 0.28);
            cursor: pointer;
            transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.4s ease;
            user-select: none;
        }}
        .artwork-stage:hover .album-art-card {{
            transform: scale(1.05);
            box-shadow: 
                0 25px 50px -10px rgba(0, 0, 0, 0.9),
                0 0 45px rgba(99, 102, 241, 0.45);
        }}

        .album-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
            transition: transform 0.5s ease;
        }}
        .artwork-stage:hover .album-img {{
            transform: scale(1.08);
        }}

        /* Quick Play Overlay on Artwork */
        .art-overlay {{
            position: absolute;
            inset: 0;
            background: linear-gradient(to top, rgba(0, 0, 0, 0.6) 0%, transparent 60%);
            opacity: 0;
            transition: opacity 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .artwork-stage:hover .art-overlay,
        .artwork-stage.is-playing .art-overlay {{
            opacity: 1;
        }}
        .center-play-badge {{
            width: 52px;
            height: 52px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.22);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.35);
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
            transition: transform 0.2s ease, background 0.2s ease;
        }}
        .center-play-badge:hover {{
            transform: scale(1.12);
            background: rgba(255, 255, 255, 0.35);
        }}

        /* Interactive Floating Cursor Tooltip */
        .cursor-tooltip {{
            position: fixed;
            z-index: 1000;
            pointer-events: none;
            background: rgba(15, 23, 42, 0.88);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #f8fafc;
            padding: 8px 16px;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 500;
            white-space: nowrap;
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.6);
            opacity: 0;
            transform: translateZ(0);
            transition: opacity 0.15s ease;
        }}
        .cursor-tooltip.visible {{
            opacity: 1;
        }}
        .tooltip-artist {{
            font-weight: 700;
            color: #ffffff;
        }}

        /* Track Info */
        .track-title {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.5rem;
            font-weight: 700;
            line-height: 1.3;
            margin-bottom: 8px;
            color: #ffffff;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            letter-spacing: -0.01em;
        }}
        .track-artist {{
            font-size: 0.95rem;
            color: #94a3b8;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        .artist-dot {{
            color: #6366f1;
            font-size: 0.6rem;
        }}

        /* ── Glass Interactive Audio Control Bar ── */
        .audio-glass-panel {{
            background: rgba(9, 12, 22, 0.65);
            border-radius: 20px;
            padding: 16px 20px;
            margin-bottom: 24px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.05);
        }}
        .scrubber-container {{
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 9999px;
            position: relative;
            cursor: pointer;
            margin-bottom: 12px;
            transition: height 0.2s ease;
        }}
        .scrubber-container:hover {{
            height: 9px;
        }}
        .scrubber-progress {{
            position: absolute;
            top: 0;
            left: 0;
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #6366f1 0%, #ec4899 100%);
            border-radius: 9999px;
            transition: width 0.1s linear;
        }}
        .scrubber-thumb {{
            position: absolute;
            right: -6px;
            top: 50%;
            transform: translateY(-50%) scale(0);
            width: 14px;
            height: 14px;
            border-radius: 50%;
            background: #ffffff;
            box-shadow: 0 0 10px rgba(255, 255, 255, 0.8);
            transition: transform 0.2s ease;
        }}
        .scrubber-container:hover .scrubber-thumb {{
            transform: translateY(-50%) scale(1);
        }}
        .time-row {{
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: #64748b;
            font-variant-numeric: tabular-nums;
            margin-bottom: 14px;
            font-weight: 500;
        }}

        /* Center Control Row */
        .controls-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 4px;
        }}
        .ctrl-btn {{
            background: transparent;
            border: none;
            color: #94a3b8;
            cursor: pointer;
            padding: 8px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
        }}
        .ctrl-btn:hover {{
            color: #ffffff;
            background: rgba(255, 255, 255, 0.08);
            transform: scale(1.08);
        }}
        .play-pause-circle {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            color: #ffffff;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 8px 24px -4px rgba(99, 102, 241, 0.6);
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }}
        .play-pause-circle:hover {{
            transform: scale(1.1);
            box-shadow: 0 12px 30px -4px rgba(99, 102, 241, 0.8);
        }}

        /* Volume Box */
        .vol-container {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .vol-slider {{
            width: 70px;
            height: 4px;
            -webkit-appearance: none;
            background: rgba(255, 255, 255, 0.15);
            border-radius: 2px;
            outline: none;
            cursor: pointer;
        }}
        .vol-slider::-webkit-slider-thumb {{
            -webkit-appearance: none;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #ffffff;
            cursor: pointer;
        }}

        /* ── Action Buttons ── */
        .btn-stack {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .btn-row {{
            display: flex;
            gap: 12px;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 9px;
            font-family: 'Outfit', sans-serif;
            font-size: 0.95rem;
            font-weight: 600;
            padding: 14px 22px;
            border-radius: 16px;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            border: none;
            flex: 1;
            position: relative;
            overflow: hidden;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            color: #ffffff;
            box-shadow: 0 8px 24px -6px rgba(99, 102, 241, 0.55);
        }}
        .btn-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 14px 32px -6px rgba(99, 102, 241, 0.75);
        }}
        .btn-secondary {{
            background: rgba(255, 255, 255, 0.06);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
        }}
        .btn-secondary:hover {{
            background: rgba(255, 255, 255, 0.12);
            color: #ffffff;
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.2);
        }}
        .btn-video {{
            background: rgba(239, 68, 68, 0.14);
            color: #fca5a5;
            border: 1px solid rgba(239, 68, 68, 0.28);
        }}
        .btn-video:hover {{
            background: rgba(239, 68, 68, 0.24);
            color: #ffffff;
            transform: translateY(-2px);
            box-shadow: 0 8px 24px -4px rgba(239, 68, 68, 0.4);
        }}

        /* Info Footer */
        .info-bar {{
            margin-top: 24px;
            font-size: 0.76rem;
            color: #64748b;
            display: flex;
            justify-content: space-between;
            padding: 0 6px;
            font-weight: 500;
        }}

        /* Toast Feedback */
        .toast {{
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: #10b981;
            color: white;
            padding: 12px 24px;
            border-radius: 9999px;
            font-size: 0.88rem;
            font-weight: 600;
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
            box-shadow: 0 12px 30px rgba(16, 185, 129, 0.45);
            z-index: 2000;
        }}
        .toast.show {{
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }}

        /* Responsive Mobile Styling */
        @media (max-width: 580px) {{
            .artwork-stage:hover .vinyl-container,
            .artwork-stage.is-playing .vinyl-container {{
                transform: translate(-50%, -50%) translateX(-55px);
            }}
            .artwork-stage {{
                width: 200px;
                height: 200px;
            }}
            .album-art-card {{
                width: 200px;
                height: 200px;
            }}
            .vinyl-container {{
                width: 180px;
                height: 180px;
            }}
            .glass-card {{
                padding: 24px 20px;
                border-radius: 26px;
            }}
            .cursor-tooltip {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="bg-glow glow-1"></div>
    <div class="bg-glow glow-2"></div>
    <div class="bg-glow glow-3"></div>

    <!-- Interactive Cursor-Following Tooltip -->
    <div class="cursor-tooltip" id="cursorTooltip">
        <span class="tooltip-artist">{escaped_artist}</span> &nbsp;•&nbsp; {escaped_title}
    </div>

    <div class="player-wrapper">
        <div class="glass-card">
            <!-- Badge Bar -->
            <div class="badge-bar">
                <span class="badge"><span class="pulse-dot"></span> EchoAPI Master Stream</span>
                <span class="badge badge-live">128kbps MP3</span>
            </div>

            <!-- Artwork & Sliding Vinyl Record Stage -->
            <div class="artwork-stage" id="artworkStage">
                <!-- Vinyl Record with Spin Animation & Actual Song Center Label -->
                <div class="vinyl-container">
                    <div class="vinyl-disc" id="vinylDisc">
                        <div class="vinyl-center-label">
                            <img class="vinyl-label-img" src="{thumbnail}" alt="{escaped_title}"
                                 onerror="if(!this.dataset.triedSd){{this.dataset.triedSd='1';this.src='https://i.ytimg.com/vi/{video_id}/sddefault.jpg';}}else{{this.src='https://i.ytimg.com/vi/{video_id}/hqdefault.jpg';}}">
                            <div class="vinyl-center-hole"></div>
                        </div>
                    </div>
                </div>

                <!-- Album Art Card with Actual Song Image -->
                <div class="album-art-card" id="artCard" title="Click to Play / Pause">
                    <img class="album-img" src="{thumbnail}" alt="{escaped_title}"
                         onerror="if(!this.dataset.triedSd){{this.dataset.triedSd='1';this.src='https://i.ytimg.com/vi/{video_id}/sddefault.jpg';}}else{{this.src='https://i.ytimg.com/vi/{video_id}/hqdefault.jpg';}}">
                    <div class="art-overlay">
                        <div class="center-play-badge" id="overlayPlayBadge">
                            <svg id="overlayPlayIcon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                                <polygon points="6 3 20 12 6 21 6 3"></polygon>
                            </svg>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Title & Artist -->
            <h1 class="track-title">{escaped_title}</h1>
            <p class="track-artist">
                <span>{escaped_artist}</span>
                <span class="artist-dot">●</span>
                <span>{duration_str}</span>
            </p>

            <!-- Hidden Audio Element -->
            <audio id="audioElement" preload="auto">
                <source src="{stream_url}" type="audio/mpeg">
                Your browser does not support audio streaming.
            </audio>

            <!-- Interactive Glass Audio Controls -->
            <div class="audio-glass-panel">
                <div class="scrubber-container" id="scrubber">
                    <div class="scrubber-progress" id="progressBar">
                        <div class="scrubber-thumb"></div>
                    </div>
                </div>

                <div class="time-row">
                    <span id="currentTime">0:00</span>
                    <span id="totalTime">{duration_str}</span>
                </div>

                <div class="controls-row">
                    <!-- Rewind 10s -->
                    <button class="ctrl-btn" id="rewindBtn" title="Rewind 10s">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 17l-5-5 5-5M18 17l-5-5 5-5"/>
                        </svg>
                    </button>

                    <!-- Center Play/Pause -->
                    <button class="play-pause-circle" id="mainPlayBtn" title="Play / Pause">
                        <svg id="mainPlayIcon" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                            <polygon points="6 3 20 12 6 21 6 3"></polygon>
                        </svg>
                    </button>

                    <!-- Forward 10s -->
                    <button class="ctrl-btn" id="forwardBtn" title="Forward 10s">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M13 17l5-5-5-5M6 17l5-5-5-5"/>
                        </svg>
                    </button>

                    <!-- Volume / Mute -->
                    <div class="vol-container">
                        <button class="ctrl-btn" id="muteBtn" title="Mute / Unmute">
                            <svg id="volumeIcon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                                <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                            </svg>
                        </button>
                        <input type="range" class="vol-slider" id="volumeSlider" min="0" max="1" step="0.05" value="1">
                    </div>
                </div>
            </div>

            <!-- Action Buttons Stack -->
            <div class="btn-stack">
                <a href="{stream_url}" target="_blank" class="btn btn-primary" id="directStreamBtn">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                    </svg>
                    Direct Audio Stream Link
                </a>

                <div class="btn-row">
                    <a href="{video_url}" target="_blank" class="btn btn-video">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect>
                            <line x1="7" y1="2" x2="7" y2="22"></line>
                            <line x1="17" y1="2" x2="17" y2="22"></line>
                            <line x1="2" y1="12" x2="22" y2="12"></line>
                            <line x1="2" y1="7" x2="7" y2="7"></line>
                            <line x1="2" y1="17" x2="7" y2="17"></line>
                            <line x1="17" y1="17" x2="22" y2="17"></line>
                            <line x1="17" y1="7" x2="22" y2="7"></line>
                        </svg>
                        Watch Video
                    </a>

                    <button class="btn btn-secondary" onclick="copyStreamLink()">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                        Copy Stream URL
                    </button>
                </div>
            </div>

            <!-- Footer Meta -->
            <div class="info-bar">
                <span>ID: {video_id}</span>
                <span>Engine: {method}</span>
            </div>
        </div>
    </div>

    <!-- Toast Notification -->
    <div class="toast" id="toast">✓ Stream URL copied to clipboard!</div>

    <script>
        const audio = document.getElementById('audioElement');
        const stage = document.getElementById('artworkStage');
        const artCard = document.getElementById('artCard');
        const mainPlayBtn = document.getElementById('mainPlayBtn');
        const mainPlayIcon = document.getElementById('mainPlayIcon');
        const overlayPlayBadge = document.getElementById('overlayPlayBadge');
        const overlayPlayIcon = document.getElementById('overlayPlayIcon');
        const scrubber = document.getElementById('scrubber');
        const progressBar = document.getElementById('progressBar');
        const currentTimeSpan = document.getElementById('currentTime');
        const totalTimeSpan = document.getElementById('totalTime');
        const volumeSlider = document.getElementById('volumeSlider');
        const muteBtn = document.getElementById('muteBtn');
        const rewindBtn = document.getElementById('rewindBtn');
        const forwardBtn = document.getElementById('forwardBtn');
        const tooltip = document.getElementById('cursorTooltip');

        const playSVG = '<polygon points="6 3 20 12 6 21 6 3"></polygon>';
        const pauseSVG = '<rect x="6" y="4" width="4" height="16" rx="1"></rect><rect x="14" y="4" width="4" height="16" rx="1"></rect>';

        // ── Toggle Play / Pause ──
        function togglePlay() {{
            if (audio.paused) {{
                audio.play().then(() => {{
                    setPlayState(true);
                }}).catch(err => {{
                    console.log("Autoplay blocked or waiting for user interaction:", err);
                }});
            }} else {{
                audio.pause();
                setPlayState(false);
            }}
        }}

        function setPlayState(isPlaying) {{
            if (isPlaying) {{
                stage.classList.add('is-playing');
                mainPlayIcon.innerHTML = pauseSVG;
                overlayPlayIcon.innerHTML = pauseSVG;
            }} else {{
                stage.classList.remove('is-playing');
                mainPlayIcon.innerHTML = playSVG;
                overlayPlayIcon.innerHTML = playSVG;
            }}
        }}

        artCard.addEventListener('click', togglePlay);
        mainPlayBtn.addEventListener('click', togglePlay);
        audio.addEventListener('play', () => setPlayState(true));
        audio.addEventListener('pause', () => setPlayState(false));

        // Spacebar quick shortcut
        document.addEventListener('keydown', (e) => {{
            if (e.code === 'Space' && e.target.tagName !== 'INPUT') {{
                e.preventDefault();
                togglePlay();
            }}
        }});

        // ── Cursor-Following Tooltip on Artwork ──
        artCard.addEventListener('mousemove', (e) => {{
            const offset = 18;
            const tooltipWidth = tooltip.offsetWidth || 220;
            const tooltipHeight = tooltip.offsetHeight || 40;

            let x = e.clientX + offset;
            let y = e.clientY - tooltipHeight - 12;

            if (x + tooltipWidth > window.innerWidth) {{
                x = e.clientX - tooltipWidth - offset;
            }}
            if (y < 10) {{
                y = e.clientY + offset;
            }}

            tooltip.style.left = `${{x}}px`;
            tooltip.style.top = `${{y}}px`;
            tooltip.classList.add('visible');
        }});

        artCard.addEventListener('mouseleave', () => {{
            tooltip.classList.remove('visible');
        }});

        // ── Time & Progress Formatting ──
        function formatTime(seconds) {{
            if (isNaN(seconds)) return "0:00";
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${{mins}}:${{secs < 10 ? '0' : ''}}${{secs}}`;
        }}

        audio.addEventListener('timeupdate', () => {{
            if (audio.duration) {{
                const percent = (audio.currentTime / audio.duration) * 100;
                progressBar.style.width = `${{percent}}%`;
                currentTimeSpan.textContent = formatTime(audio.currentTime);
            }}
        }});

        audio.addEventListener('loadedmetadata', () => {{
            if (audio.duration && !isNaN(audio.duration)) {{
                totalTimeSpan.textContent = formatTime(audio.duration);
            }}
        }});

        // Scrubber Seeking
        scrubber.addEventListener('click', (e) => {{
            const rect = scrubber.getBoundingClientRect();
            const pos = (e.clientX - rect.left) / rect.width;
            if (audio.duration) {{
                audio.currentTime = pos * audio.duration;
            }}
        }});

        // Skip 10s Forward / Backward
        rewindBtn.addEventListener('click', () => {{
            audio.currentTime = Math.max(0, audio.currentTime - 10);
        }});
        forwardBtn.addEventListener('click', () => {{
            if (audio.duration) {{
                audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
            }}
        }});

        // ── Volume & Mute ──
        volumeSlider.addEventListener('input', (e) => {{
            audio.volume = parseFloat(e.target.value);
            audio.muted = (audio.volume === 0);
        }});

        muteBtn.addEventListener('click', () => {{
            audio.muted = !audio.muted;
            if (audio.muted) {{
                volumeSlider.value = 0;
            }} else {{
                volumeSlider.value = audio.volume || 1;
            }}
        }});

        // ── Copy Stream URL ──
        function copyStreamLink() {{
            const link = "{stream_url}";
            navigator.clipboard.writeText(link).then(() => {{
                const toast = document.getElementById('toast');
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show'), 2600);
            }});
        }}

        // Attempt soft autoplay on load
        window.addEventListener('load', () => {{
            audio.play().then(() => {{
                setPlayState(true);
            }}).catch(() => {{
                setPlayState(false);
            }});
        }});
    </script>
</body>
</html>
"""
