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
                artist="Neha Kakkar & Rohanpreet Singh"
                music="Baarish Mein Tum"
                albumArt="https://i.ytimg.com/vi/BOT2xL1-p6Q/maxresdefault.jpg"
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
