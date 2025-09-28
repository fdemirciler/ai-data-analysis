import { useEffect, useState, useCallback } from "react";

interface SSEEvent {
  type: 'analysis_start' | 'progress' | 'partial' | 'result' | 'error' | 'done';
  data: any;
}

interface UseSSEOptions {
  onEvent?: (event: SSEEvent) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

export function useSSE(url: string | null, options: UseSSEOptions = {}) {
  const [isConnected, setIsConnected] = useState(false);
  const [eventSource, setEventSource] = useState<EventSource | null>(null);

  const connect = useCallback(() => {
    if (!url) return;

    const es = new EventSource(url);
    
    es.onopen = () => {
      setIsConnected(true);
      options.onOpen?.();
    };

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        options.onEvent?.(parsed);
      } catch (error) {
        console.error('Failed to parse SSE message:', error);
      }
    };

    es.onerror = (error) => {
      setIsConnected(false);
      options.onError?.(error);
    };

    // Handle specific event types
    ['analysis_start', 'progress', 'partial', 'result', 'error', 'done'].forEach(eventType => {
      es.addEventListener(eventType, (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data);
          options.onEvent?.({ type: eventType as any, data });
        } catch (error) {
          console.error(`Failed to parse ${eventType} event:`, error);
        }
      });
    });

    setEventSource(es);
  }, [url, options]);

  const disconnect = useCallback(() => {
    if (eventSource) {
      eventSource.close();
      setEventSource(null);
      setIsConnected(false);
      options.onClose?.();
    }
  }, [eventSource, options]);

  useEffect(() => {
    if (url) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [url, connect, disconnect]);

  return {
    isConnected,
    connect,
    disconnect,
    eventSource
  };
}

// Mock SSE for development
export function useMockSSE(onEvent: (event: SSEEvent) => void) {
  const simulateAnalysis = useCallback(async (message: string) => {
    // Simulate analysis start
    onEvent({ type: 'analysis_start', data: { timestamp: new Date().toISOString() } });
    
    await new Promise(resolve => setTimeout(resolve, 500));

    // Simulate progress events
    const steps = ['llm_classify', 'ast_validate', 'fast_exec'];
    for (let i = 0; i < steps.length; i++) {
      onEvent({ 
        type: 'progress', 
        data: { 
          step: steps[i], 
          percent: ((i + 1) / steps.length) * 100, 
          message: `Processing step ${i + 1}/${steps.length}` 
        } 
      });
      await new Promise(resolve => setTimeout(resolve, 800));
    }

    // Simulate streaming partial content
    const response = "Based on your data analysis request, I can see several interesting patterns. Let me break this down for you:";
    const words = response.split(' ');
    
    for (let i = 0; i < words.length; i++) {
      onEvent({ 
        type: 'partial', 
        data: { 
          text: words.slice(0, i + 1).join(' ') + (i < words.length - 1 ? '' : '') 
        } 
      });
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Simulate final result with mock data
    onEvent({ 
      type: 'result', 
      data: { 
        text: response,
        code: `import pandas as pd
import matplotlib.pyplot as plt

# Load and analyze data
df = pd.read_csv('data.csv')
summary = df.describe()
print(summary)`,
        table: [
          { column: 'sales', mean: 1250.5, std: 234.2, count: 100 },
          { column: 'profit', mean: 425.3, std: 89.7, count: 100 },
          { column: 'customers', mean: 856.2, std: 145.8, count: 100 }
        ],
        artifacts: [
          { type: 'csv', url: '#', filename: 'analysis_results.csv' }
        ]
      } 
    });

    await new Promise(resolve => setTimeout(resolve, 300));

    // Simulate completion
    onEvent({ 
      type: 'done', 
      data: { 
        summary: 'Analysis completed successfully',
        persistedSessionId: 'session-' + Date.now()
      } 
    });
  }, [onEvent]);

  return { simulateAnalysis };
}