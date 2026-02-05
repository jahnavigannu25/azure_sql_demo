import React, { useRef, useEffect } from 'react';
import { Message } from './Message';
import { TypingIndicator } from './TypingIndicator';

export function ChatArea({ messages, isTyping }) {
    const scrollRef = useRef(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, isTyping]);

    return (
        <div className="flex-1 overflow-y-auto px-4 py-8 scroll-smooth" ref={scrollRef}>
            <div className="max-w-3xl mx-auto space-y-8">
                {messages.map((msg) => (
                    <Message key={msg.id} message={msg} />
                ))}
                {isTyping && (
                    <div className="flex gap-4">
                        <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
                            <div className="w-4 h-4 rounded-full bg-gradient-to-br from-brand-primary to-brand-secondary" />
                        </div>
                        <div className="flex items-center">
                            <TypingIndicator />
                        </div>
                    </div>
                )}
                <div className="h-4" /> {/* Spacer */}
            </div>
        </div>
    );
}
