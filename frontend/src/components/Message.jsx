import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Code, Terminal, ChevronDown, ChevronRight, User, Sparkles, Copy, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown'; // Assuming user might want markdown support, though not explicitly requested, it's safer to keep simple first.

export function Message({ message }) {
  const isAi = message.role === 'ai';
  const isSystem = message.role === 'system';

  if (isSystem) {
    return (
      <div className="flex justify-center my-6">
        <span className="text-[10px] font-mono uppercase tracking-widest text-gray-600 bg-white/5 px-3 py-1.5 rounded-full border border-white/5">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`flex gap-5 ${!isAi ? 'flex-row-reverse' : ''} group`}
    >
      {/* Avatar */}
      <div className={`
        w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-lg
        ${isAi 
          ? 'bg-gradient-to-br from-dark-800 to-black border border-white/10' 
          : 'bg-gradient-to-br from-brand-primary to-brand-secondary text-white shadow-brand-primary/20'}
      `}>
        {isAi ? (
           <div className="relative w-full h-full rounded-xl overflow-hidden flex items-center justify-center">
             <div className="absolute inset-0 bg-white/5 opacity-50" />
             <Sparkles className="w-4 h-4 text-brand-accent relative z-10" />
           </div>
        ) : (
           <span className="text-xs font-bold">ME</span>
        )}
      </div>

      {/* Content */}
      <div className={`flex flex-col gap-2 max-w-[85%] sm:max-w-[75%] ${!isAi ? 'items-end' : 'items-start'}`}>
        
        {/* Text Bubble */}
        <div className={`
          px-6 py-4 text-[15px] leading-relaxed shadow-lg backdrop-blur-sm
          ${!isAi 
            ? 'bg-gradient-to-br from-brand-primary to-brand-secondary text-white rounded-2xl rounded-tr-sm' 
            : 'bg-white/[0.03] border border-white/10 text-gray-200 rounded-2xl rounded-tl-sm hover:border-white/20 transition-colors'}
        `}>
          {message.content}
        </div>

        {/* SQL Block */}
        {message.sql && (
          <QueryBlock sql={message.sql} />
        )}

        {/* Table Render */}
        {message.tableHtml && (
          <motion.div 
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="w-full overflow-hidden rounded-2xl border border-white/10 bg-black/40 shadow-2xl mt-2"
          >
            <div className="flex items-center justify-between px-4 py-2 bg-white/5 border-b border-white/5">
               <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Result Set</span>
               <div className="flex gap-1.5">
                 <div className="w-2 h-2 rounded-full bg-red-500/20" />
                 <div className="w-2 h-2 rounded-full bg-yellow-500/20" />
                 <div className="w-2 h-2 rounded-full bg-green-500/20" />
               </div>
            </div>
            <div 
              className="overflow-x-auto p-0 custom-scrollbar max-h-[400px]"
              dangerouslySetInnerHTML={{ __html: message.tableHtml }} 
            />
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

function QueryBlock({ sql }) {
  const [isOpen, setIsOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyToClipboard = (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full mt-2 rounded-xl border border-white/10 bg-black/40 overflow-hidden shadow-lg">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-3 px-4 py-3 text-xs font-mono text-gray-400 hover:text-gray-200 hover:bg-white/5 transition-all"
      >
        <Terminal className="w-3.5 h-3.5 text-brand-accent" />
        <span className="font-semibold tracking-wide">GENERATED SQL</span>
        <div className={`ml-auto transform transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}>
           <ChevronDown className="w-3.5 h-3.5" />
        </div>
      </button>
      
      {isOpen && (
        <div className="relative group">
          <pre className="p-5 text-xs font-mono text-blue-300 overflow-x-auto border-t border-white/10 bg-black/20 custom-scrollbar leading-relaxed">
            <code>{sql}</code>
          </pre>
          <button 
            onClick={copyToClipboard}
            className="absolute top-3 right-3 p-1.5 rounded-lg bg-white/10 text-gray-400 hover:text-white hover:bg-white/20 transition-all opacity-0 group-hover:opacity-100"
          >
            {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
          </button>
        </div>
      )}
    </div>
  );
}
