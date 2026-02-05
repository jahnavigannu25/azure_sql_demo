import React from 'react';

export function TypingIndicator() {
    return (
        <div className="flex gap-1.5 p-1">
            <div className="w-2 h-2 bg-brand-primary rounded-full animate-bounce" style={{ animationDelay: '0s' }} />
            <div className="w-2 h-2 bg-brand-secondary rounded-full animate-bounce" style={{ animationDelay: '0.15s' }} />
            <div className="w-2 h-2 bg-brand-accent rounded-full animate-bounce" style={{ animationDelay: '0.3s' }} />
        </div>
    );
}
