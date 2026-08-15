'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { backendApi, BackendItem } from '@/lib/backend-api';
import { useToast } from '@/hooks/use-toast';

interface StatusBarContextType {
  activeItems: BackendItem[];
  completedItems: BackendItem[];
  failedItems: BackendItem[];
  isPaused: boolean;
  addDownload: (url: string, quality?: number) => Promise<void>;
  togglePause: () => Promise<void>;
  clearCompleted: () => Promise<void>;
  cancelTask: (id: string) => Promise<void>;
  refreshQueue: () => Promise<void>;
}

const StatusBarContext = createContext<StatusBarContextType | null>(null);

export function StatusBarProvider({ children }: { children: React.ReactNode }) {
  const [activeItems, setActiveItems] = useState<BackendItem[]>([]);
  const [completedItems, setCompletedItems] = useState<BackendItem[]>([]);
  const [failedItems, setFailedItems] = useState<BackendItem[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const { toast } = useToast();

  const refreshQueue = useCallback(async () => {
    try {
      const data = await backendApi.getQueue();
      if (data) {
        setActiveItems(data.active || []);
        setCompletedItems(data.completed || []);
        setFailedItems(data.failed || []);
        setIsPaused(!!data.is_paused);
      }
    } catch (e) {
      console.warn('Queue fetch error:', e);
    }
  }, []);

  useEffect(() => {
    refreshQueue();

    const ws = backendApi.connectWebSocket((msg) => {
      if (msg.type === 'init' || msg.type === 'tick') {
        if (msg.data.active_items) setActiveItems(msg.data.active_items);
      } else if (msg.type === 'item_completed') {
        toast({
          title: "Download Concluído",
          description: msg.data.title || "Faixa FLAC finalizada.",
        });
        refreshQueue();
      } else if (msg.type === 'item_failed') {
        toast({
          variant: "destructive",
          title: "Falha no Download",
          description: msg.data.error_message || "Ocorreu um erro no processamento.",
        });
        refreshQueue();
      }
    });

    const interval = setInterval(refreshQueue, 3500);

    return () => {
      clearInterval(interval);
      if (ws) ws.close();
    };
  }, [refreshQueue, toast]);

  const addDownload = async (url: string, quality?: number) => {
    try {
      const res = await backendApi.addToQueue([url], quality);
      if (res.success) {
        toast({
          title: "Adicionado à Fila",
          description: `Download enfileirado com sucesso.`,
        });
        refreshQueue();
      }
    } catch (e: any) {
      toast({
        variant: "destructive",
        title: "Erro ao Enfileirar",
        description: e.message || "Não foi possível conectar ao servidor.",
      });
    }
  };

  const togglePause = async () => {
    if (isPaused) {
      await backendApi.resumeQueue();
      setIsPaused(false);
    } else {
      await backendApi.pauseQueue();
      setIsPaused(true);
    }
  };

  const clearCompleted = async () => {
    await backendApi.clearCompleted();
    setCompletedItems([]);
    setFailedItems([]);
  };

  const cancelTask = async (id: string) => {
    await backendApi.cancelTask(id);
    refreshQueue();
  };

  return (
    <StatusBarContext.Provider
      value={{
        activeItems,
        completedItems,
        failedItems,
        isPaused,
        addDownload,
        togglePause,
        clearCompleted,
        cancelTask,
        refreshQueue,
      }}
    >
      {children}
    </StatusBarContext.Provider>
  );
}

export const useStatusBar = () => {
  const context = useContext(StatusBarContext);
  if (!context) throw new Error('useStatusBar must be used within StatusBarProvider');
  return context;
};
