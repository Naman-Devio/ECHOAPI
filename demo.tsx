"use client";

import MusicArtwork from './components/ui/music-artwork';

export default function Home() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-950 px-4 relative overflow-hidden">
      <div className="text-center space-y-12 relative z-10">
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-center">
              <MusicArtwork
                artist="Drake"
                music="Search & Rescue"
                albumArt="https://cdn.21st.dev/assets/mirror/76/767edce9899286a9a394f3a6c4adbff5e90e0b783150cbad131ee141326db922.jpg"
                isSong={true}
                isLoading={false}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
