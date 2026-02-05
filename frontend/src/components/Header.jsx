import React from 'react';
import { Menu, LogOut, Shield } from 'lucide-react';

export function Header({ user, activeProject, toggleSidebar }) {
    return (
        <header className="h-20 px-8 flex items-center justify-between sticky top-0 z-40 transition-all duration-300">
            <div className="flex items-center gap-4">
                <button
                    onClick={toggleSidebar}
                    className="p-2.5 -ml-2.5 text-gray-400 hover:text-white hover:bg-white/5 rounded-xl transition-all active:scale-95"
                >
                    <Menu className="w-5 h-5" />
                </button>

                <div className="flex flex-col">
                    <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Active Project</span>
                    <div className="flex items-center gap-2">
                        <span className="text-lg font-medium text-white tracking-tight">
                            {activeProject || 'Overview'}
                        </span>
                        <div className={`w-2 h-2 rounded-full ${activeProject ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-gray-600'}`} />
                    </div>
                </div>
            </div>

            <div className="flex items-center gap-6">
                {user?.is_admin && (
                    <a
                        href="/admin"
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-brand-primary/10 border border-brand-primary/20 text-brand-primary text-xs font-bold hover:bg-brand-primary/20 transition-all"
                    >
                        <Shield className="w-3 h-3" />
                        ADMIN
                    </a>
                )}

                <div className="flex items-center gap-4 pl-6 border-l border-white/5">
                    <div className="flex flex-col items-end hidden sm:flex">
                        <span className="text-sm font-medium text-white">{user?.name || 'User'}</span>
                        <span className="text-xs text-gray-500">{user?.email}</span>
                    </div>

                    <div className="relative group">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-brand-primary to-brand-secondary p-[2px] cursor-pointer shadow-lg shadow-brand-primary/20 group-hover:shadow-brand-primary/40 transition-all">
                            <div className="w-full h-full rounded-full bg-dark-900 flex items-center justify-center text-sm font-bold text-white">
                                {user?.name?.[0] || 'U'}
                            </div>
                        </div>

                        {/* Dropdown for logout could go here, but for now we keep the direct button */}
                        <a
                            href="/logout"
                            className="absolute -bottom-2 -right-2 w-6 h-6 rounded-full bg-dark-800 border border-white/10 flex items-center justify-center text-gray-400 hover:text-red-400 hover:bg-white/5 transition-all shadow-lg"
                            title="Sign Out"
                        >
                            <LogOut className="w-3 h-3" />
                        </a>
                    </div>
                </div>
            </div>
        </header>
    );
}
