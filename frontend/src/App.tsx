import React, { useState, useEffect } from "react";
import { NewSidebar } from "./components/NewSidebar";
import { NewChatArea } from "./components/NewChatArea";
import { FloatingChatInput } from "./components/FloatingChatInput";
import { FloatingControls } from "./components/FloatingControls";
import { MockAuth } from "./components/MockAuth";
import { useAuth } from "./context/AuthContext";
import { useChat } from "./context/ChatContext";

export default function App() {
  const { user, login, logout } = useAuth();
  const { 
    sessions, 
    activeSessionId, 
    messages, 
    isLoading,
    selectSession,
    createNewSession,
    deleteSessionById,
    deleteAll,
    sendMessage,
    usage
  } = useChat();

  const [isDark, setIsDark] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  }, [isDark]);

  // Auto-open sidebar on desktop
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024) {
        setIsSidebarOpen(true);
      } else {
        setIsSidebarOpen(false);
      }
    };

    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleSendMessage = async (content: string, file?: File) => {
    await sendMessage({ content, file });
  };

  const handleDeleteAllData = async () => {
    if (confirm("Are you sure you want to delete all your data? This action cannot be undone.")) {
      await deleteAll();
    }
  };

  if (!user) {
    return <MockAuth onLogin={login} />;
  }

  return (
    <div className="h-screen flex bg-gray-50 dark:bg-gray-950 transition-colors">
      {/* Collapsible Sidebar */}
      <NewSidebar
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
        onNewChat={createNewSession}
        onSelectChat={selectSession}
        onDeleteChat={deleteSessionById}
        onDeleteAllData={handleDeleteAllData}
        onLogout={logout}
        sessions={sessions}
        activeSessionId={activeSessionId}
        userName={user.name}
        userEmail={user.email}
        usage={usage}
      />

      {/* Main Content Area */}
      <main 
        className={`flex-1 flex flex-col transition-all duration-200 ${isSidebarOpen ? 'ml-0 lg:ml-80' : 'ml-0 lg:ml-16'}`}
      >
        {/* Floating Top Controls */}
        <FloatingControls
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          isDark={isDark}
          onToggleDark={() => setIsDark(!isDark)}
        />

        {/* Chat Area with Infinite Scroll */}
        <NewChatArea 
          messages={messages} 
          isLoading={isLoading}
        />

        {/* Floating Input Box */}
        <FloatingChatInput
          onSendMessage={handleSendMessage}
          disabled={isLoading}
        />
      </main>
    </div>
  );
}
