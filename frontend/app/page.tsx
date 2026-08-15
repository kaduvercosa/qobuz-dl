'use client';

import React, { useEffect, useState } from 'react';
import { SearchBar } from '@/components/search-bar/search-bar';
import { ReleaseCard, ReleaseProps } from '@/components/release-card';
import { ModeToggle } from '@/components/mode-toggle';
import { Particles } from '@/components/particles';
import { backendApi } from '@/lib/backend-api';
import { Disc3, Sparkles, SlidersHorizontal, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';

export default function Home() {
  const [releases, setReleases] = useState<ReleaseProps[]>([]);
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<any>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { toast } = useToast();

  const loadReleases = async () => {
    setLoading(true);
    try {
      const data = await backendApi.getReleases(18);
      if (data && data.albums?.items) {
        const formatted: ReleaseProps[] = data.albums.items.map((item: any) => ({
          id: item.id,
          title: item.title,
          artist: item.artist?.name || 'Artista',
          year: String(item.release_date_original || '2024').slice(0, 4),
          hires: item.maximum_bit_depth >= 24,
          coverUrl: item.image?.large || item.image?.small,
          type: 'album',
          qobuzUrl: `https://open.qobuz.com/album/${item.id}`,
        }));
        setReleases(formatted);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const loadSettings = async () => {
    try {
      const cfg = await backendApi.getConfig();
      setConfig(cfg);
    } catch (e) {
      console.warn(e);
    }
  };

  useEffect(() => {
    loadReleases();
    loadSettings();
  }, []);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!config) return;
    try {
      await backendApi.updateConfig(config);
      toast({ title: 'Configurações salvas com sucesso!' });
      setSettingsOpen(false);
    } catch (err: any) {
      toast({ variant: 'destructive', title: 'Erro ao salvar', description: err.message });
    }
  };

  return (
    <main className="relative min-h-screen pb-24 overflow-x-hidden">
      <Particles className="opacity-40" />

      {/* Top Header */}
      <header className="sticky top-0 z-30 w-full border-b border-border/40 bg-background/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-primary flex items-center justify-center text-primary-foreground shadow-md shadow-primary/20">
              <Disc3 className="h-5 w-5 animate-spin-slow" />
            </div>
            <div>
              <h1 className="font-bold text-sm tracking-wide">QOBUZ-DL</h1>
              <p className="text-[10px] text-muted-foreground font-mono">LOSSLESS AUDIO ENGINE</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
              <DialogTrigger asChild>
                <Button variant="ghost" size="icon" className="rounded-full">
                  <SlidersHorizontal className="h-4 w-4" />
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-md">
                <DialogHeader>
                  <DialogTitle className="text-base font-bold">Ajustes do Motor de Download</DialogTitle>
                </DialogHeader>
                {config && (
                  <form onSubmit={handleSaveSettings} className="space-y-4 pt-2 text-xs">
                    <div className="space-y-1.5">
                      <Label>Diretório de Download</Label>
                      <Input
                        value={config.paths?.download_dir || ''}
                        onChange={(e) =>
                          setConfig({ ...config, paths: { ...config.paths, download_dir: e.target.value } })
                        }
                        className="text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label>Estrutura de Pastas</Label>
                      <Input
                        value={config.paths?.folder_format || ''}
                        onChange={(e) =>
                          setConfig({ ...config, paths: { ...config.paths, folder_format: e.target.value } })
                        }
                        className="text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label>Formato do Arquivo</Label>
                      <Input
                        value={config.paths?.track_format || ''}
                        onChange={(e) =>
                          setConfig({ ...config, paths: { ...config.paths, track_format: e.target.value } })
                        }
                        className="text-xs"
                      />
                    </div>
                    <Button type="submit" className="w-full text-xs">
                      Salvar Alterações
                    </Button>
                  </form>
                )}
              </DialogContent>
            </Dialog>

            <ModeToggle />
          </div>
        </div>
      </header>

      {/* Hero Search Section */}
      <section className="max-w-5xl mx-auto px-4 pt-12 pb-8 text-center flex flex-col items-center gap-4">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-semibold tracking-wide">
          <Sparkles className="h-3.5 w-3.5" />
          <span>FLAC 24-BIT / 192 KHZ STUDIO QUALITY</span>
        </div>

        <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight">
          Explore e Baixe em Alta Resolução
        </h2>
        <p className="text-muted-foreground text-xs sm:text-sm max-w-md">
          Pesquise no catálogo oficial do Qobuz ou cole qualquer link de álbum ou faixa para baixar diretamente.
        </p>

        <div className="w-full mt-4">
          <SearchBar />
        </div>
      </section>

      {/* Featured / Releases Section */}
      <section className="max-w-7xl mx-auto px-4 mt-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-bold text-lg tracking-tight">Lançamentos Recentes</h3>
          <Button variant="ghost" size="sm" onClick={loadReleases} className="text-xs gap-1">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
        </div>

        {loading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="aspect-square rounded-2xl bg-muted/60 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {releases.map((rel) => (
              <ReleaseCard key={rel.id} release={rel} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
