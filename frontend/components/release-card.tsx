'use client';

import React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Download, Music, Disc } from 'lucide-react';
import { useStatusBar } from '@/lib/status-bar/context';

export interface ReleaseProps {
  id: string | number;
  title: string;
  artist: string;
  album?: string;
  year?: string | number;
  quality?: string;
  coverUrl?: string;
  hires?: boolean;
  type?: 'album' | 'track';
  qobuzUrl?: string;
}

export function ReleaseCard({ release }: { release: ReleaseProps }) {
  const { addDownload } = useStatusBar();

  const handleDownload = () => {
    const url = release.qobuzUrl || `https://open.qobuz.com/${release.type || 'album'}/${release.id}`;
    addDownload(url);
  };

  return (
    <Card className="group relative overflow-hidden transition-all duration-300 hover:shadow-xl hover:border-primary/50">
      <div className="relative aspect-square w-full overflow-hidden bg-muted">
        {release.coverUrl ? (
          <img
            src={release.coverUrl}
            alt={release.title}
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-secondary/50">
            <Disc className="h-12 w-12 text-muted-foreground opacity-50" />
          </div>
        )}
        <div className="absolute top-2 right-2 flex gap-1">
          <span className="rounded-full bg-black/70 px-2 py-0.5 text-[10px] font-bold text-white backdrop-blur-md">
            {release.hires ? 'HI-RES' : 'LOSSLESS'}
          </span>
        </div>
      </div>
      <CardContent className="p-4 flex flex-col justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-semibold text-sm line-clamp-1 group-hover:text-primary transition-colors">
            {release.title}
          </h3>
          <p className="text-xs text-muted-foreground line-clamp-1">{release.artist}</p>
          {release.year && <span className="text-[10px] text-muted-foreground">{release.year}</span>}
        </div>
        <Button size="sm" onClick={handleDownload} className="w-full gap-2 text-xs font-semibold">
          <Download className="h-3.5 w-3.5" />
          Baixar FLAC
        </Button>
      </CardContent>
    </Card>
  );
}
