import React from 'react';
import { Database, Check, Square, CheckSquare, Circle, CheckCircle2, Layers, ChevronDown } from 'lucide-react';
import { motion } from 'framer-motion';

export function Sidebar({ 
  isOpen, 
  projects, 
  activeProject, 
  onSelectProject, 
  schema, 
  selectedTables, 
  onToggleTable, 
  onSelectAll 
}) {
  const allSelected = schema.length > 0 && selectedTables.length === schema.length;
  const anySelected = selectedTables.length > 0;

  return (
    <motion.aside 
      initial={{ x: -280 }}
      animate={{ x: isOpen ? 0 : -280 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
      className="fixed inset-y-0 left-0 w-[280px] bg-black/40 backdrop-blur-2xl border-r border-white/5 z-50 flex flex-col"
    >
      {/* Brand */}
      <div className="h-24 flex items-center gap-4 px-6 border-b border-white/5 bg-white/[0.02]">
        <div className="w-10 h-10 relative flex items-center justify-center">
            <div className="absolute inset-0 bg-brand-primary/20 blur-xl rounded-full"></div>
            <img src="/logo.svg" alt="Lumina Logo" className="w-10 h-10 relative z-10 drop-shadow-[0_0_10px_rgba(6,182,212,0.5)]" />
        </div>
        <div className="flex flex-col">
            <span className="font-bold text-2xl tracking-tight text-white bg-clip-text text-transparent bg-gradient-to-r from-white via-blue-100 to-gray-400">
            LUMINA
            </span>
        </div>
      </div>

      <div className="p-6 flex-1 overflow-y-auto custom-scrollbar">
        {/* Workspace Picker */}
        <div className="mb-8">
          <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-3 block">Workspace</label>
          <div className="relative group">
            <select 
              value={activeProject}
              onChange={(e) => onSelectProject(e.target.value)}
              className="w-full bg-white/[0.03] text-sm text-gray-200 rounded-xl p-3 pl-10 appearance-none border border-white/5 hover:border-white/10 focus:border-brand-primary focus:outline-none transition-all cursor-pointer"
            >
              <option value="" disabled>Select Workspace</option>
              {projects.map(p => (
                <option key={p} value={p} className="bg-dark-800">{p}</option>
              ))}
            </select>
            <Layers className="w-4 h-4 text-gray-400 absolute left-3 top-3.5 pointer-events-none group-hover:text-brand-primary transition-colors" />
            <ChevronDown className="w-4 h-4 text-gray-400 absolute right-3 top-3.5 pointer-events-none" />
          </div>
        </div>

        {/* Schema List */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Data Sources</label>
            {schema.length > 0 && (
              <button 
                onClick={onSelectAll}
                className="text-[10px] font-bold text-brand-primary hover:text-brand-accent transition-all duration-200 tracking-wider flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-brand-primary/10 group/btn"
              >
                <div className="relative w-3.5 h-3.5 flex items-center justify-center">
                  {anySelected ? (
                    <CheckCircle2 className="w-3.5 h-3.5 absolute text-brand-primary" />
                  ) : (
                    <Circle className="w-3.5 h-3.5 absolute opacity-70" />
                  )}
                </div>
                <span className="min-w-[85px] text-left transition-all duration-200">
                  {anySelected ? 'UNSELECT ALL' : 'SELECT ALL'}
                </span>
              </button>
            )}
          </div>

          <div className="space-y-1">
            {schema.length === 0 ? (
              <div className="text-sm text-gray-600 italic py-6 text-center border border-dashed border-white/5 rounded-xl bg-white/[0.01]">
                No active data
              </div>
            ) : (
              schema.map(table => {
                const isSelected = selectedTables.includes(table);
                return (
                  <div 
                    key={table}
                    onClick={() => onToggleTable(table)}
                    className={`
                      group flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-all duration-200 border border-transparent
                      ${isSelected ? 'bg-brand-primary/10 border-brand-primary/20 text-white' : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'}
                    `}
                  >
                    <div className={`
                      w-4 h-4 rounded border flex items-center justify-center transition-all
                      ${isSelected ? 'bg-brand-primary border-brand-primary' : 'border-gray-600 group-hover:border-gray-400 bg-transparent'}
                    `}>
                       {isSelected && <Check className="w-3 h-3 text-white" />}
                    </div>
                    <span className="text-sm truncate font-medium">{table}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
      
      {/* Footer */}
      <div className="p-4 border-t border-white/5">
        <div className="text-[10px] text-gray-600 text-center font-mono">
          v2.0.4 &bull; Connected to Azure SQL
        </div>
      </div>
    </motion.aside>
  );
}
