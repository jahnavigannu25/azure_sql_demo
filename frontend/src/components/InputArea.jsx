import React, { useState } from 'react';
import { Send, Sparkles, Command } from 'lucide-react';

export function InputArea({ onSend, disabled }) {
  const [text, setText] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (text.trim() && !disabled) {
      onSend(text);
      setText('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="pb-8 pt-4 px-4 bg-gradient-to-t from-black via-black/80 to-transparent z-30">
      <div className="max-w-3xl mx-auto">
        <form 
          onSubmit={handleSubmit}
          className={`
            relative flex items-end gap-2 p-2 rounded-[26px]
            bg-white/[0.05] backdrop-blur-xl border border-white/10 
            focus-within:border-brand-primary/50 focus-within:ring-1 focus-within:ring-brand-primary/50 focus-within:bg-black/40
            transition-all duration-300 shadow-2xl
          `}
        >
          <div className="pl-4 pb-3">
            <Sparkles className={`w-5 h-5 text-brand-primary transition-opacity ${text ? 'opacity-100' : 'opacity-50'}`} />
          </div>
          
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            rows={1}
            placeholder={disabled ? "Thinking..." : "Ask Insight anything about your data..."}
            className="flex-1 bg-transparent border-none outline-none text-white placeholder-gray-500 min-h-[44px] max-h-[120px] py-3 resize-none custom-scrollbar leading-relaxed"
            style={{ height: 'auto', minHeight: '44px' }}
            onInput={(e) => {
              e.target.style.height = 'auto';
              e.target.style.height = e.target.scrollHeight + 'px';
            }}
          />
          
          <div className="p-1">
            <button 
              type="button" 
              disabled={!text.trim() || disabled}
              onClick={handleSubmit}
              className={`
                w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300
                ${text.trim() && !disabled
                  ? 'bg-gradient-to-tr from-brand-primary to-brand-secondary text-white shadow-lg shadow-brand-primary/25 hover:scale-105 active:scale-95' 
                  : 'bg-white/5 text-gray-600 cursor-not-allowed'}
              `}
            >
              <Send className="w-4 h-4 ml-0.5" />
            </button>
          </div>
        </form>
        <div className="flex justify-center items-center gap-4 mt-4 text-[10px] text-gray-600 font-medium tracking-wide">
           <span className="flex items-center gap-1.5">
             <Command className="w-3 h-3" />
             AI generated responses can be inaccurate. Verify important data.
           </span>
        </div>
      </div>
    </div>
  );
}
