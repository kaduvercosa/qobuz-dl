'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Search, Loader2, X, Plus } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { backendApi } from '@/lib/backend-api';
import { useStatusBar } from '@/lib/status-bar/context';

export function SearchBar({ onSelectRelease }: { onSelectRelease?: (item: any) => void }) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<{ albums: any[]; tracks: any[]; artists: any[] }>({
    albums: [],
    tracks: [],
    artists: [],
  });
  const [showDropdown, setShowDropdown] = useState(false);
  const { addDownload } = useStatusBar();
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (!query.trim() || query.length < 2) {
      setResults({ albums: [], tracks: [], artists: [] });
      setShowDropdown(false);
      return;
    }

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await backendApi.searchCatalog(query, 6);
        setResults({
          albums: data.albums?.items || [],
          tracks: data.tracks?.items || [],
          artists: data.artists?.items || [],
        });
        setShowDropdown(true);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [query]);

  const handleDownloadDirect = (url: string) => {
    addDownload(url);
    setShowDropdown(false);
    setQuery('');
  };

  const handlePasteUrl = () => {
    if (query.includes('qobuz.com')) {
      handleDownloadDirect(query.trim());
    }
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-2xl mx-auto">
      <div className="relative flex items-center">
        <Search className="absolute left-3.5 h-4 w-4 text-muted-foreground" />
        <Input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => (results.albums.length > 0 || results.tracks.length > 0) && setShowDropdown(true)}
          placeholder="Busque por Artista, Álbum ou cole link do Qobuz..."
          className="pl-10 pr-24 py-6 rounded-full text-sm bg-card/70 backdrop-blur-md border-border/80 focus-visible:ring-primary shadow-sm"
        />
        <div className="absolute right-2 flex items-center gap-1">
          {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground mr-1" />}
          {query.includes('qobuz.com') ? (
            <Button size="sm" onClick={handlePasteUrl} className="rounded-full px-3 py-1 text-xs">
              <Plus className="h-3.5 w-3.5 mr-1" /> Baixar
            </Button>
          ) : query ? (
            <Button variant="ghost" size="icon" onClick={() => setQuery('')} className="h-7 w-7 rounded-full">
              <X className="h-3.5 w-3.5" />
            </Button>
          ) : null}
        </div>
      </div>

      {showDropdown && (results.albums.length > 0 || results.tracks.length > 0) && (
        <div className="absolute top-full mt-2 w-full rounded-2xl bg-card border border-border shadow-2xl z-50 overflow-hidden backdrop-blur-xl max-h-[420px] overflow-y-auto">
          {results.albums.length > 0 && (
            <div className="p-2 border-b border-border/40">
              <p className="text-[11px] font-bold text-muted-foreground px-3 py-1 uppercase tracking-wider">Álbuns</p>
              {results.albums.slice(0, 4).map((alb) => (
                <div
                  key={alb.id}
                  onClick={() => handleDownloadDirect(`https://open.qobuz.com/album/${alb.id}`)}
                  className="flex items-center justify-between p-2 rounded-xl hover:bg-muted/70 cursor-pointer transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <img
                      src={alb.image?.small || alb.image?.large}
                      alt={alb.title}
                      className="h-10 w-10 rounded-lg object-cover bg-secondary"
                    />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold truncate">{alb.title}</p>
                      <p className="text-[11px] text-muted-foreground truncate">{alb.artist?.name}</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                    {alb.maximum_bit_depth ? `${alb.maximum_bit_depth}B` : 'FLAC'}
                  </span>
                </div>
              ))}
            </div>
          )}

          {results.tracks.length > 0 && (
            <div className="p-2">
              <p className="text-[11px] font-bold text-muted-foreground px-3 py-1 uppercase tracking-wider">Faixas</p>
              {results.tracks.slice(0, 5).map((tr) => (
                <div
                  key={tr.id}
                  onClick={() => handleDownloadDirect(`https://open.qobuz.com/track/${tr.id}`)}
                  className="flex items-center justify-between p-2 rounded-xl hover:bg-muted/70 cursor-pointer transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <img
                      src={tr.album?.image?.small || tr.album?.image?.large}
                      alt={tr.title}
                      className="h-9 w-9 rounded-md object-cover bg-secondary"
                    />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold truncate">{tr.title}</p>
                      <p className="text-[11px] text-muted-foreground truncate">
                        {tr.performer?.name || tr.album?.artist?.name}
                      </p>
                    </div>
                  </div>
                  <span className="text-[10px] text-muted-foreground">
                    {Math.floor(tr.duration / 60)}:{String(tr.duration % 60).padStart(2, '0')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
