import { useState, useRef, useEffect } from 'react';
import { Mic, MicOff, Send, Volume2, Trash2 } from 'lucide-react';
import { voiceQuery } from '../lib/api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  timestamp: string;
  toolCalls?: { tool: string }[];
  processingMs?: number;
}

export function VoiceConsole() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [caseId, setCaseId] = useState('synth_wrist_001');
  const [aoCode, setAoCode] = useState('23-A2');
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendQuery = async (text: string) => {
    if (!text.trim()) return;

    const userMsg: Message = {
      role: 'user',
      text,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const result = await voiceQuery(text, caseId);
      const assistantMsg: Message = {
        role: 'assistant',
        text: result.response,
        timestamp: new Date().toLocaleTimeString(),
        toolCalls: result.tool_calls,
        processingMs: result.processing_time_ms,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        timestamp: new Date().toLocaleTimeString(),
      }]);
    } finally {
      setLoading(false);
    }
  };

  const toggleRecording = () => {
    if (recording) {
      setRecording(false);
      // TODO: Stop recording, send audio to /api/v1/voice/speak
    } else {
      setRecording(true);
      // TODO: Start recording via MediaRecorder API
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold" style={{ color: 'var(--accent)' }}>
          <Volume2 size={24} className="inline mr-2" />
          Voice Console
        </h1>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-sm">
            <label style={{ color: 'var(--text-muted)' }}>Case:</label>
            <input
              value={caseId}
              onChange={e => setCaseId(e.target.value)}
              className="px-2 py-1 rounded text-sm font-mono w-40"
              style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <label style={{ color: 'var(--text-muted)' }}>AO:</label>
            <input
              value={aoCode}
              onChange={e => setAoCode(e.target.value)}
              className="px-2 py-1 rounded text-sm font-mono w-20"
              style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
            />
          </div>
          <button
            onClick={() => setMessages([])}
            className="p-1.5 rounded hover:bg-white/10"
            title="Clear chat"
          >
            <Trash2 size={16} style={{ color: 'var(--text-muted)' }} />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div
        className="flex-1 overflow-auto rounded-lg p-4 space-y-3"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
      >
        {messages.length === 0 && (
          <div className="text-center py-8" style={{ color: 'var(--text-muted)' }}>
            <Volume2 size={48} className="mx-auto mb-4 opacity-30" />
            <p className="text-lg">Intraoperative Voice Console</p>
            <p className="text-sm mt-2">Type a surgical question or click the mic to speak.</p>
            <p className="text-xs mt-1 font-mono">Consultative mode — the AI provides information, never commands.</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className="max-w-[80%] rounded-lg px-4 py-2.5"
              style={{
                background: msg.role === 'user' ? '#1a73e8' : 'var(--bg)',
                border: msg.role === 'assistant' ? '1px solid var(--border)' : 'none',
              }}
            >
              <div className="text-sm whitespace-pre-wrap">{msg.text}</div>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[10px] opacity-50">{msg.timestamp}</span>
                {msg.toolCalls && msg.toolCalls.length > 0 && (
                  <span className="text-[10px] px-1 rounded" style={{ background: '#ab47bc33', color: '#ce93d8' }}>
                    {msg.toolCalls.map(t => t.tool).join(', ')}
                  </span>
                )}
                {msg.processingMs && (
                  <span className="text-[10px] opacity-50">{msg.processingMs}ms</span>
                )}
              </div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="rounded-lg px-4 py-2.5" style={{ background: 'var(--bg)', border: '1px solid var(--border)' }}>
              <div className="flex gap-1">
                <span className="w-2 h-2 rounded-full animate-bounce" style={{ background: 'var(--accent)', animationDelay: '0ms' }} />
                <span className="w-2 h-2 rounded-full animate-bounce" style={{ background: 'var(--accent)', animationDelay: '150ms' }} />
                <span className="w-2 h-2 rounded-full animate-bounce" style={{ background: 'var(--accent)', animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="mt-3 flex gap-2">
        <button
          onClick={toggleRecording}
          className={`p-3 rounded-lg transition-colors ${recording ? 'animate-pulse' : ''}`}
          style={{
            background: recording ? '#d32f2f' : 'var(--bg-card)',
            border: '1px solid var(--border)',
          }}
          title={recording ? 'Stop recording' : 'Start recording'}
        >
          {recording ? <MicOff size={20} /> : <Mic size={20} style={{ color: 'var(--accent)' }} />}
        </button>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendQuery(input)}
          placeholder="Type a surgical question... (e.g., 'Check K-wire trajectory for the distal fragment')"
          className="flex-1 px-4 py-2 rounded-lg text-sm"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
          disabled={loading}
        />
        <button
          onClick={() => sendQuery(input)}
          disabled={loading || !input.trim()}
          className="p-3 rounded-lg"
          style={{ background: '#1a73e8', color: 'white', opacity: loading || !input.trim() ? 0.5 : 1 }}
        >
          <Send size={20} />
        </button>
      </div>
    </div>
  );
}
