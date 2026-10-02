"""
🎵 EchoAPI Interactive Web Player
Renders a modern, responsive, glassmorphic audio/video player interface.
Allows users and bot testers to stream, play, and test direct playback links.
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
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: radial-gradient(circle at 20% 20%, #1e1136 0%, #0a0c16 60%, #05070e 100%);
            color: #f1f5f9;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 24px 16px;
            overflow-x: hidden;
        }}
        .bg-glow {{
            position: fixed;
            width: 450px;
            height: 450px;
            border-radius: 50%;
            filter: blur(120px);
            opacity: 0.25;
            pointer-events: none;
            z-index: 0;
        }}
        .glow-1 {{ top: -100px; left: -100px; background: #6366f1; }}
        .glow-2 {{ bottom: -100px; right: -100px; background: #ec4899; }}
        
        .container {{
            position: relative;
            z-index: 1;
            width: 100%;
            max-width: 520px;
        }}
        .card {{
            background: rgba(18, 22, 38, 0.75);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 28px;
            padding: 32px 28px;
            box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(255, 255, 255, 0.05);
            text-align: center;
            transition: transform 0.3s ease;
        }}
        .badge-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 6px 12px;
            border-radius: 9999px;
            background: rgba(99, 102, 241, 0.15);
            color: #818cf8;
            border: 1px solid rgba(99, 102, 241, 0.3);
        }}
        .badge-live {{
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            border-color: rgba(16, 185, 129, 0.3);
        }}
        .pulse {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: currentColor;
            animation: pulse 1.8s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.4; transform: scale(0.85); }}
        }}
        .art-container {{
            position: relative;
            width: 220px;
            height: 220px;
            margin: 0 auto 28px;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 16px 36px -10px rgba(0, 0, 0, 0.8), 0 0 30px rgba(99, 102, 241, 0.25);
        }}
        .art-img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            transition: transform 0.4s ease;
        }}
        .art-container:hover .art-img {{
            transform: scale(1.05);
        }}
        .title {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.45rem;
            font-weight: 700;
            line-height: 1.3;
            margin-bottom: 8px;
            color: #f8fafc;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        .artist {{
            font-size: 0.95rem;
            color: #94a3b8;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
        }}
        .verified-icon {{
            color: #38bdf8;
            font-size: 0.85rem;
        }}
        .audio-wrapper {{
            background: rgba(10, 14, 26, 0.6);
            border-radius: 16px;
            padding: 12px 14px;
            margin-bottom: 24px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}
        audio {{
            width: 100%;
            height: 40px;
            outline: none;
            border-radius: 12px;
        }}
        .btn-group {{
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
            gap: 8px;
            font-family: 'Outfit', sans-serif;
            font-size: 0.95rem;
            font-weight: 600;
            padding: 14px 20px;
            border-radius: 14px;
            text-decoration: none;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            border: none;
            flex: 1;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            color: #ffffff;
            box-shadow: 0 8px 24px -6px rgba(99, 102, 241, 0.5);
        }}
        .btn-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 30px -6px rgba(99, 102, 241, 0.7);
        }}
        .btn-secondary {{
            background: rgba(255, 255, 255, 0.06);
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .btn-secondary:hover {{
            background: rgba(255, 255, 255, 0.12);
            color: #ffffff;
            transform: translateY(-2px);
        }}
        .btn-video {{
            background: rgba(239, 68, 68, 0.15);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.3);
        }}
        .btn-video:hover {{
            background: rgba(239, 68, 68, 0.25);
            transform: translateY(-2px);
        }}
        .info-pill {{
            margin-top: 20px;
            font-size: 0.78rem;
            color: #64748b;
            display: flex;
            justify-content: space-between;
            padding: 0 6px;
        }}
        .toast {{
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: #10b981;
            color: white;
            padding: 10px 20px;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 600;
            opacity: 0;
            transition: all 0.3s ease;
            box-shadow: 0 10px 25px rgba(16, 185, 129, 0.4);
            z-index: 100;
        }}
        .toast.show {{
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }}
    </style>
</head>
<body>
    <div class="bg-glow glow-1"></div>
    <div class="bg-glow glow-2"></div>

    <div class="container">
        <div class="card">
            <div class="badge-bar">
                <span class="badge"><span class="pulse"></span> EchoAPI Stream</span>
                <span class="badge badge-live">128kbps MP3</span>
            </div>

            <div class="art-container">
                <img class="art-img" src="{thumbnail}" alt="{escaped_title}" onerror="this.src='https://img.youtube.com/vi/{video_id}/hqdefault.jpg'">
            </div>

            <h1 class="title">{escaped_title}</h1>
            <p class="artist">
                <span>{escaped_artist}</span>
                <span class="verified-icon">●</span>
                <span>{duration_str}</span>
            </p>

            <div class="audio-wrapper">
                <audio id="audioPlayer" controls autoplay preload="auto">
                    <source src="{stream_url}" type="audio/mpeg">
                    Your browser does not support audio streaming.
                </audio>
            </div>

            <div class="btn-group">
                <a href="{stream_url}" target="_blank" class="btn btn-primary" id="playBtn">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                    </svg>
                    Direct Audio Stream Link
                </a>

                <div class="btn-row">
                    <a href="{video_url}" target="_blank" class="btn btn-video">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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

                    <button class="btn btn-secondary" onclick="copyLink()">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                        Copy URL
                    </button>
                </div>
            </div>

            <div class="info-pill">
                <span>ID: {video_id}</span>
                <span>Engine: {method}</span>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">✓ Stream URL copied to clipboard!</div>

    <script>
        function copyLink() {{
            const link = "{stream_url}";
            navigator.clipboard.writeText(link).then(() => {{
                const toast = document.getElementById('toast');
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show'), 2500);
            }});
        }}
    </script>
</body>
</html>
"""
