import { useState, useEffect } from "react";
import { Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { ChatArea } from "./components/ChatArea";
import { ChatInput } from "./components/ChatInput";
import { MockAuth } from "./components/MockAuth";
import { useMockSSE } from "./hooks/useSSE";

interface User {
  name: string;
  email: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  code?: string;
  chart?: any;
  table?: Array<Record<string, any>>;
  artifacts?: Array<{ type: string; url: string; filename: string }>;
  isStreaming?: boolean;
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [isDark, setIsDark] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [currentStreamingMessageId, setCurrentStreamingMessageId] = useState<string | null>(null);

  const { simulateAnalysis } = useMockSSE((event) => {
    switch (event.type) {
      case 'analysis_start':
        setIsLoading(true);
        break;
        
      case 'partial':
        if (currentStreamingMessageId) {
          setMessages(prev => prev.map(msg => 
            msg.id === currentStreamingMessageId 
              ? { ...msg, content: event.data.text, isStreaming: true }
              : msg
          ));
        }
        break;
        
      case 'result':
        if (currentStreamingMessageId) {
          setMessages(prev => prev.map(msg => 
            msg.id === currentStreamingMessageId 
              ? { 
                  ...msg, 
                  content: event.data.text,
                  code: event.data.code,
                  table: event.data.table,
                  artifacts: event.data.artifacts,
                  isStreaming: false 
                }
              : msg
          ));
        }
        break;
        
      case 'done':
        setIsLoading(false);
        setCurrentStreamingMessageId(null);
        break;
        
      case 'error':
        setIsLoading(false);
        setCurrentStreamingMessageId(null);
        break;
    }
  });

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  }, [isDark]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) {
        setIsSidebarOpen(true);
      } else {
        setIsSidebarOpen(false);
      }
    };

    if (window.innerWidth >= 768) {
      setIsSidebarOpen(true);
    }

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleLogin = (userData: User) => {
    setUser(userData);
  };

  const handleLogout = () => {
    setUser(null);
    setMessages([]);
  };

  const handleSendMessage = async (content: string, file?: File) => {
    if (!content.trim() && !file) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: file ? `${content}\n\n[Uploaded: ${file.name}]` : content,
      timestamp: new Date().toLocaleTimeString()
    };

    setMessages(prev => [...prev, userMessage]);

    const assistantMessageId = `assistant-${Date.now()}`;
    const assistantMessage: Message = {
      id: assistantMessageId,
      role: "assistant",
      content: "",
      timestamp: new Date().toLocaleTimeString(),
      isStreaming: true
    };

    setMessages(prev => [...prev, assistantMessage]);
    setCurrentStreamingMessageId(assistantMessageId);

    if (file) {
      console.log("Mock file upload:", file.name, file.size);
    }

    await simulateAnalysis(content);
  };

  const handleNewChat = () => {
    setMessages([]);
  };

  const handleSelectChat = (chatId: string) => {
    console.log("Select chat:", chatId);
  };

  const handleDeleteChat = (chatId: string) => {
    console.log("Delete chat:", chatId);
  };

  const handleDeleteAllData = () => {
    if (confirm("Are you sure you want to delete all your data? This action cannot be undone.")) {
      setMessages([]);
      console.log("All data deleted");
    }
  };

  if (!user) {
    return <MockAuth onLogin={handleLogin} />;
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      <Header
        isDark={isDark}
        onToggleDark={() => setIsDark(!isDark)}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
      />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
          onNewChat={handleNewChat}
          onSelectChat={handleSelectChat}
          onDeleteChat={handleDeleteChat}
          onDeleteAllData={handleDeleteAllData}
          onLogout={handleLogout}
          sessions={[]}
          activeSessionId={null}
          upload={{ status: "idle" }}
        />

        <main className="flex-1 flex flex-col transition-all duration-200">
          <ChatArea 
            messages={messages} 
            isLoading={isLoading}
          />

          <ChatInput
            onSendMessage={handleSendMessage}
            disabled={isLoading}
          />
        </main>
      </div>
    </div>
  );
}