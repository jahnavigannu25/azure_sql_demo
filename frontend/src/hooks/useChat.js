import { useState, useEffect, useCallback } from 'react';

export function useChat() {
  const [user, setUser] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState('');
  const [schema, setSchema] = useState([]);
  const [selectedTables, setSelectedTables] = useState([]);
  const [messages, setMessages] = useState([
    { 
      id: 'intro', 
      role: 'ai', 
      content: 'Hello. I am Insight. Select a workspace to begin analysis.',
      timestamp: new Date()
    }
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);

  // Initial load
  useEffect(() => {
    fetch('/api/me')
      .then(res => {
        if (res.status === 401 || res.status === 403) {
             window.location.href = '/login';
             throw new Error('Not logged in');
        }
        if (!res.ok) throw new Error('Network response was not ok');
        return res.json();
      })
      .then(data => {
        setUser(data);
        const projs = data.projects.map(p => p.project);
        setProjects(projs);
      })
      .catch(err => {
        console.error("Auth error", err);
        // Redirect to login if needed, or handle error
        if (window.location.pathname !== '/') {
           // Maybe redirect to /login
        }
      });
  }, []);

  // Load schema when project changes
  useEffect(() => {
    if (!activeProject) return;

    setSchema([]);
    setSelectedTables([]);
    
    fetch(`/api/accessible-schema?project=${encodeURIComponent(activeProject)}`)
      .then(res => res.json())
      .then(data => {
        const tables = data.tables || [];
        setSchema(tables);
        setSelectedTables(tables); // Default select all
        
        // Add system message
        addMessage({
          role: 'system',
          content: `Workspace switched to **${activeProject}**. Loaded ${tables.length} tables.`
        });
      })
      .catch(err => console.error(err));
  }, [activeProject]);

  const addMessage = useCallback((msg) => {
    setMessages(prev => [...prev, { ...msg, id: Math.random().toString(36), timestamp: new Date() }]);
  }, []);

  const sendMessage = async (text) => {
    if (!text.trim() || !activeProject) return;

    // User message
    const userMsg = { role: 'user', content: text };
    addMessage(userMsg);
    setIsLoading(true);
    setIsTyping(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          project: activeProject,
          selectedTables
        })
      });
      
      const data = await res.json();
      
      if (data.error) {
        addMessage({ role: 'ai', content: `Error: ${data.error}`, isError: true });
      } else {
        addMessage({
          role: 'ai',
          content: data.summary,
          sql: data.sql,
          tableHtml: data.table_html
        });
      }
    } catch (err) {
      addMessage({ role: 'ai', content: "Network error. Please try again.", isError: true });
    } finally {
      setIsLoading(false);
      setIsTyping(false);
    }
  };

  const toggleTable = (tableName) => {
    setSelectedTables(prev => 
      prev.includes(tableName) 
        ? prev.filter(t => t !== tableName)
        : [...prev, tableName]
    );
  };

  const toggleAll = () => {
    console.log('toggleAll called. current selected:', selectedTables.length, 'schema:', schema.length);
    if (selectedTables.length > 0) {
      setSelectedTables([]);
    } else {
      setSelectedTables(schema);
    }
  };

  useEffect(() => {
    console.log('Selected Tables updated:', selectedTables);
  }, [selectedTables]);

  return {
    user,
    projects,
    activeProject,
    setActiveProject,
    schema,
    selectedTables,
    toggleTable,
    toggleAll,
    messages,
    sendMessage,
    isLoading,
    isTyping
  };
}
