'use client';

import React, { useState } from 'react';
import { useStatusBar } from '@/lib/status-bar/context';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Play, Pause, Trash2, ListMusic, CheckCircle2, AlertCircle } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';

export function StatusBar() {
  const { activeItems, completedItems, failedItems, isPaused, togglePause, clearCompleted, cancelTask } = useStatusBar();
  const [openQueue, setOpenQueue] = useState(false);

  const activeItem = activeItems[0];
  const totalCount = activeItems.length + completedItems.length + failedItems.length;

  if (totalCount === 0) return null;

  return (
    <>
      <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 w-11/12 max-w-2xl bg-card/95 backdrop-blur-xl border border-border/80 shadow-2xl rounded-2xl p-3.5 flex items-center justify-between gap-4 animate-in slide-in-from-bottom-5">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {activeItem ? (
            <img
              src={activeItem.cover_url || '/placeholder.png'}
              alt={activeItem.title}
              className="h-11 w-11 rounded-lg object-cover border border-border/50 shrink-0"
            />
          ) : (
            <div className="h-11 w-11 rounded-lg bg-muted flex items-center justify-center shrink-0">
              <CheckCircle2 className="h-5 w-5 text-green-500" />
            </div>
          )}

          <div className="flex flex-col gap-1 min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold truncate">
                {activeItem ? `${activeItem.artist} - ${activeItem.title}` : 'Todos os downloads concluídos'}
              </span>
              <span className="text-[11px] font-semibold text-primary shrink-0">
                {activeItem ? `${activeItem.percent.toFixed(0)}%` : `${completedItems.length} concluído(s)`}
              </span>
            </div>

            {activeItem && (
              <Progress value={activeItem.percent} className="h-1.5 bg-muted" />
            )}

            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>{activeItem?.stage || (isPaused ? 'Pausado' : 'Pronto')}</span>
              <span>{activeItem?.speed_str || ''}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <Button variant="ghost" size="icon" onClick={togglePause} className="h-8 w-8 rounded-full">
            {isPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
          </Button>

          <Dialog open={openQueue} onOpenChange={setOpenQueue}>
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" className="rounded-full text-xs font-semibold gap-1.5 px-3">
                <ListMusic className="h-3.5 w-3.5" />
                <span>Fila ({activeItems.length})</span>
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md max-h-[80vh] overflow-hidden flex flex-col">
              <DialogHeader className="flex flex-row items-center justify-between border-b pb-3">
                <DialogTitle className="text-base font-bold">Fila de Downloads</DialogTitle>
                <Button variant="ghost" size="sm" onClick={clearCompleted} className="text-xs text-muted-foreground">
                  <Trash2 className="h-3.5 w-3.5 mr-1" /> Limpar
                </Button>
              </DialogHeader>

              <div className="flex-1 overflow-y-auto divide-y divide-border/40 py-2">
                {activeItems.map((item) => (
                  <div key={item.item_id} className="py-2.5 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-semibold truncate">{item.title}</p>
                      <p className="text-[11px] text-muted-foreground truncate">{item.artist}</p>
                      <span className="text-[10px] text-primary font-bold">{item.stage}</span>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => cancelTask(item.item_id)} className="h-7 text-xs text-destructive">
                      Cancelar
                    </Button>
                  </div>
                ))}

                {completedItems.map((item) => (
                  <div key={item.item_id} className="py-2 flex items-center justify-between text-muted-foreground">
                    <div className="min-w-0">
                      <p className="text-xs truncate">{item.title}</p>
                      <p className="text-[10px]">{item.artist}</p>
                    </div>
                    <span className="text-[10px] text-green-500 font-bold">✓ Concluído</span>
                  </div>
                ))}
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </div>
    </>
  );
}
