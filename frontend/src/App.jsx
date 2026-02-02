import React, { useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { ChatArea } from './components/ChatArea';
import { InputArea } from './components/InputArea';
import { useChat } from './hooks/useChat';

function App() {
  const { 
    user, 
    projects, 
    activeProject, 
    setActiveProject, 
    schema, 
    selectedTables, 
    toggleTable,
    selectAllTables,
    messages,
    sendMessage,
    isLoading,
    isTyping
  } = useChat();

  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Sidebar */}
      <Sidebar 
        isOpen={isSidebarOpen}
        projects={projects}
        activeProject={activeProject}
        onSelectProject={setActiveProject}
        schema={schema}
        selectedTables={selectedTables}
        onToggleTable={toggleTable}
        onSelectAll={selectAllTables}
      />

      {/* Main Content */}
      <div 
        className={`flex-1 flex flex-col h-full transition-all duration-300 ease-spring ${isSidebarOpen ? 'ml-[280px]' : 'ml-0'}`}
      >
        <Header 
          user={user} 
          activeProject={activeProject} 
          toggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        />
        
        <main className="flex-1 flex flex-col min-h-0 relative">
          <ChatArea 
            messages={messages} 
            isTyping={isTyping}
          />
          
          <InputArea 
            onSend={sendMessage} 
            disabled={isLoading || isTyping} 
          />
        </main>
      </div>
    </div>
  );
}

export default App;
