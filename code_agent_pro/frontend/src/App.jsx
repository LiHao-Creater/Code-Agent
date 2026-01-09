import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import mermaid from 'mermaid';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Terminal, Activity, Check, Copy, Loader2,
  GitMerge, BookOpen, Lightbulb, Layers, Zap,
  CornerDownLeft, X, AlertTriangle, MessageSquareQuote,
  CheckCircle, XCircle, ChevronRight, Shuffle
} from 'lucide-react';
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

function cn(...inputs) { return twMerge(clsx(inputs)); }

mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    darkMode: true,
    background: '#0f172a',
    primaryColor: '#6366f1',
    lineColor: '#64748b',
    textColor: '#e2e8f0',
    mainBkg: '#0f172a',
  },
  securityLevel: 'loose'
});

function App() {
  const [task, setTask] = useState('');
  const [hasStarted, setHasStarted] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  const [logs, setLogs] = useState([]);
  const [iterations, setIterations] = useState([]);
  const [finalResult, setFinalResult] = useState(null);
  const [diagramCode, setDiagramCode] = useState('');
  const [explanation, setExplanation] = useState(null);
  const [failureReport, setFailureReport] = useState(null);
  const [pivotAlert, setPivotAlert] = useState(null); // 新增状态：转型通知

  const [showDiagramModal, setShowDiagramModal] = useState(false);
  const [copied, setCopied] = useState(false);

  const logEndRef = useRef(null);
  const mermaidRef = useRef(null);
  const mermaidModalRef = useRef(null);
  const codeStreamRef = useRef('');
  const textareaRef = useRef(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px';
    }
  }, [task]);

  useEffect(() => { logEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [logs]);

  const renderMermaid = async (code, element) => {
    if (code && element) {
      try {
        element.innerHTML = '';
        const id = `mermaid-${Date.now()}`;
        const cleanCode = code.replace(/```mermaid/g, '').replace(/```/g, '').trim();
        const { svg } = await mermaid.render(id, cleanCode);
        element.innerHTML = svg;
      } catch (e) {
        element.innerHTML = `<div class="flex items-center justify-center h-full text-slate-500 text-sm font-mono">图表渲染中...</div>`;
      }
    }
  };

  useEffect(() => { if(diagramCode) renderMermaid(diagramCode, mermaidRef.current); }, [diagramCode]);
  useEffect(() => { if (showDiagramModal && diagramCode) setTimeout(() => renderMermaid(diagramCode, mermaidModalRef.current), 100); }, [showDiagramModal]);

  const handleCopy = () => {
    if (finalResult?.code) {
      const match = finalResult.code.match(/```(?:\w+)?\n([\s\S]*?)```/);
      const cleanCode = match ? match[1].trim() : finalResult.code;
      navigator.clipboard.writeText(cleanCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      startAgent();
    }
  };

  const startAgent = async () => {
    if (!task.trim()) return;
    setHasStarted(true);
    setIsProcessing(true);
    setLogs([]);
    setIterations([]);
    setFinalResult(null);
    setDiagramCode('');
    setExplanation(null);
    setFailureReport(null);
    setPivotAlert(null); // 重置转型通知
    codeStreamRef.current = '';

    try {
      const response = await fetch('http://localhost:8000/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task }),
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n\n');

        lines.forEach(line => {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.replace('data: ', ''));

              // --- 新增：处理转型事件 ---
              if (data.phase === 'feasibility_alert') {
                setPivotAlert(data.content);
              }
              // -----------------------

              if (data.phase === 'code_chunk') {
                codeStreamRef.current += data.content;
                setFinalResult(prev => ({ code: codeStreamRef.current, review: prev?.review }));
              }
              if (data.phase === 'clear_code') {
                codeStreamRef.current = '';
                setFinalResult(prev => ({ ...prev, code: '' }));
              }
              if (data.phase === 'final_code_update') setFinalResult(prev => ({ ...prev, review: data.content.review }));
              if (data.phase === 'log') setLogs(prev => [...prev, data.content]);
              if (data.phase === 'iteration') setIterations(prev => [...prev, data.data]);
              if (data.phase === 'final_code') {
                codeStreamRef.current = data.content.code;
                setFinalResult(data.content);
              }
              if (data.phase === 'diagram') setDiagramCode(data.content);
              if (data.phase === 'explanation') setExplanation(data.content);
              if (data.phase === 'failure_report') setFailureReport(data.content);
            } catch (e) {}
          }
        });
      }
    } catch (e) { setLogs(prev => [...prev, `System Error: ${e.message}`]); }
    finally { setIsProcessing(false); }
  };

  const ExplanationMarkdown = ({ content }) => (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        strong: ({node, ...props}) => <span className="font-bold text-indigo-300" {...props} />,
        ul: ({node, ...props}) => <ul className="list-disc pl-5 space-y-2 my-3 text-slate-300" {...props} />,
        li: ({node, ...props}) => <li className="leading-relaxed" {...props} />,
        p: ({node, ...props}) => <p className="mb-4 leading-relaxed text-slate-300 text-base" {...props} />,
        code: ({node, inline, ...props}) => inline
          ? <code className="bg-slate-800 px-1.5 py-0.5 rounded text-indigo-200 font-mono text-sm border border-white/10" {...props} />
          : <code className="block bg-slate-950 p-4 rounded-lg text-sm my-3 border border-white/10 font-mono text-slate-400" {...props} />,
        span: ({node, className, ...props}) => {
          if (className?.includes('katex')) return <span className={cn(className, "text-emerald-300")} {...props} />
          return <span className={className} {...props} />
        }
      }}
    >
      {content}
    </ReactMarkdown>
  );

  const renderLogItem = (log, index) => {
    let icon = <ChevronRight size={14} className="text-slate-600 mt-0.5 shrink-0" />;
    let textColor = "text-slate-400";
    let content = log;

    if (log.includes("✅")) {
      icon = <CheckCircle size={14} className="text-emerald-500 mt-0.5 shrink-0" />;
      textColor = "text-emerald-400";
      content = log.replace("✅", "").trim();
    } else if (log.includes("❌")) {
      icon = <XCircle size={14} className="text-rose-500 mt-0.5 shrink-0" />;
      textColor = "text-rose-400";
      content = log.replace("❌", "").trim();
    } else if (log.includes("⚠️") || log.includes("🔄")) {
      icon = <AlertTriangle size={14} className="text-amber-500 mt-0.5 shrink-0" />;
      textColor = "text-amber-400";
      content = log.replace("⚠️", "").replace("🔄", "").trim();
    } else if (log.includes("🏗️") || log.includes("📐") || log.includes("🧠") || log.includes("⚡") || log.includes("⚖️")) {
       textColor = "text-indigo-300";
    }

    return (
      <div key={index} className="flex gap-3 items-start leading-relaxed animate-fade-in text-xs font-mono">
        {icon}
        <span className={textColor}>{content}</span>
      </div>
    );
  };

  return (
    <div className="flex h-screen bg-[#020617] text-slate-200 font-sans selection:bg-indigo-500/30 overflow-hidden">

      {/* 左侧控制台 */}
      <motion.div
        layout
        className={cn(
          "flex-shrink-0 bg-[#020617] border-r border-white/5 flex flex-col z-20 shadow-2xl shadow-black/50 transition-all duration-700 ease-[cubic-bezier(0.25,0.1,0.25,1)]",
          hasStarted ? "w-[400px]" : "w-full items-center justify-center"
        )}
      >
        <div className={cn(
          "flex flex-col gap-8 p-8 transition-all duration-700",
          hasStarted ? "w-full h-full" : "w-[640px] max-w-full"
        )}>

          <motion.div layout className="flex items-center gap-3 select-none">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Activity className="text-white w-5 h-5" />
            </div>
            <div>
              <h1 className="font-bold tracking-tight text-xl text-white">Code Agent</h1>
            </div>
          </motion.div>

          <motion.div layout className="relative group w-full">
            <div className={cn(
              "relative bg-slate-900/50 border rounded-2xl overflow-hidden transition-all duration-300",
              "border-white/10 group-focus-within:border-indigo-500/40 group-focus-within:bg-slate-900 group-focus-within:shadow-[0_0_20px_-5px_rgba(99,102,241,0.15)]"
            )}>
              <textarea
                ref={textareaRef}
                value={task}
                onChange={e => setTask(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={hasStarted ? "请输入新任务..." : "描述您的编程需求..."}
                rows={1}
                className={cn(
                  "w-full bg-transparent text-slate-200 outline-none resize-none placeholder:text-slate-600 font-medium",
                  "custom-scrollbar leading-relaxed font-sans overflow-y-auto",
                  hasStarted
                    ? "py-4 pl-5 pr-12 text-sm max-h-[200px]"
                    : "py-6 pl-6 pr-16 text-lg max-h-[40vh]"
                )}
                style={{ minHeight: hasStarted ? '56px' : '80px' }}
              />
              <div className="absolute right-3 bottom-3">
                <button
                  onClick={startAgent}
                  disabled={isProcessing || !task.trim()}
                  className={cn(
                    "p-2 rounded-xl transition-all flex items-center justify-center",
                    task.trim() && !isProcessing
                      ? "bg-indigo-600 text-white shadow-lg hover:bg-indigo-500"
                      : "bg-slate-800 text-slate-600 cursor-not-allowed opacity-0 scale-90"
                  )}
                >
                  {isProcessing ? <Loader2 className="animate-spin" size={18}/> : <CornerDownLeft size={18} />}
                </button>
              </div>
            </div>
            {!hasStarted && (
               <motion.div initial={{opacity:0}} animate={{opacity:1}} transition={{delay:0.5}} className="absolute -bottom-8 left-2 text-xs text-slate-600 font-medium flex gap-4">
                  <span>Enter 发送</span>
                  <span>Shift+Enter 换行</span>
               </motion.div>
            )}
          </motion.div>

          {hasStarted && (
            <motion.div
              initial={{opacity:0, y:20}}
              animate={{opacity:1, y:0}}
              transition={{delay: 0.3}}
              className="flex-1 flex flex-col gap-6 overflow-hidden min-h-0"
            >
              <div className="flex-1 flex flex-col min-h-0">
                <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">
                  <Terminal size={12} /> 实时日志
                </div>
                <div className="flex-1 bg-slate-900/30 rounded-xl border border-white/5 p-4 overflow-y-auto custom-scrollbar space-y-3">
                  {logs.map((log, i) => renderLogItem(log, i))}
                  <div ref={logEndRef} />
                </div>
              </div>

              {iterations.length > 0 && (
                <div className="h-1/3 min-h-[150px] flex flex-col">
                   <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">
                    <Activity size={12} /> 迭代历史
                  </div>
                  <div className="flex-1 bg-slate-900/30 rounded-xl border border-white/5 p-2 overflow-y-auto custom-scrollbar space-y-1">
                    {iterations.map((iter, idx) => (
                      <div key={idx} className="p-3 hover:bg-white/5 rounded-lg transition-colors group cursor-default">
                        <div className="flex justify-between items-center mb-1">
                          <span className="text-[10px] font-bold text-slate-500">轮次-{iter.round}</span>
                          <span className={clsx("text-[10px] font-bold px-1.5 py-0.5 rounded", iter.review.pass ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400")}>
                            {iter.review.score}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 line-clamp-2 group-hover:line-clamp-none transition-all">
                          <ExplanationMarkdown content={iter.review.critique} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </div>
      </motion.div>

      {/* 右侧主展示区 */}
      <div className="flex-1 bg-[#020617] relative overflow-hidden flex flex-col">
        {hasStarted ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, delay: 0.2 }}
            className="flex-1 overflow-y-auto custom-scrollbar p-8 md:p-12"
          >
            <div className="max-w-6xl mx-auto space-y-12">

              {finalResult ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="space-y-10"
                >

                  {/* --- 新增：战略转型卡片 --- */}
                  {pivotAlert && (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="rounded-2xl border bg-amber-950/20 border-amber-500/30 shadow-amber-900/10 p-6 backdrop-blur-sm shadow-xl"
                    >
                      <div className="flex gap-5">
                        <div className="p-3 rounded-xl h-fit bg-amber-500/10 text-amber-400 animate-pulse">
                          <Shuffle size={24} />
                        </div>
                        <div className="space-y-3 flex-1">
                          <h3 className="text-lg font-bold tracking-wide text-amber-100 flex items-center gap-2">
                            战略转型通知 (Strategic Pivot)
                          </h3>
                          <div className="space-y-2">
                            <div className="bg-amber-950/40 p-3 rounded-lg border border-amber-500/10">
                              <span className="text-amber-500 font-bold text-xs uppercase tracking-wider block mb-1">REASON / 驳回原因</span>
                              <p className="text-amber-200/90 text-sm">{pivotAlert.reason}</p>
                            </div>
                            <div className="bg-emerald-950/20 p-3 rounded-lg border border-emerald-500/10">
                              <span className="text-emerald-500 font-bold text-xs uppercase tracking-wider block mb-1">NEW PLAN / 新方案</span>
                              <p className="text-emerald-200/90 text-sm">{pivotAlert.recommendation}</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* --- 提高建议卡片 --- */}
                  {finalResult.review && finalResult.review.pass && (
                    <motion.div
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="rounded-2xl border bg-emerald-950/20 border-emerald-500/20 shadow-emerald-900/10 p-6 backdrop-blur-sm shadow-xl"
                    >
                      <div className="flex gap-5">
                        <div className="p-3 rounded-xl h-fit bg-emerald-500/10 text-emerald-400">
                          <MessageSquareQuote size={24} />
                        </div>
                        <div className="space-y-3 flex-1">
                          <div className="flex items-center gap-3">
                            <h3 className="text-lg font-bold tracking-wide text-emerald-100">
                              提高建议
                            </h3>
                            <span className="text-xs font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300">
                              {finalResult.review.score} 分
                            </span>
                          </div>
                          <div className="text-sm leading-relaxed text-emerald-200/80">
                            <ExplanationMarkdown content={finalResult.review.critique} />
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  )}

                  {/* 代码卡片 */}
                  <div className="bg-[#0f172a]/50 rounded-2xl border border-white/5 overflow-hidden shadow-2xl">
                    <div className="flex items-center justify-between px-6 py-4 bg-[#0f172a] border-b border-white/5">
                      <div className="flex items-center gap-3">
                        <div className={cn("w-2.5 h-2.5 rounded-full shadow-lg", finalResult.review?.pass ? "bg-emerald-500 shadow-emerald-500/20" : "bg-amber-500 shadow-amber-500/20")}></div>
                        <span className="text-xl font-bold text-white tracking-wide">生成代码</span>
                      </div>
                      <button onClick={handleCopy} className="text-xs font-medium text-slate-500 hover:text-white transition flex items-center gap-1.5 bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-lg">
                        {copied ? <Check size={14}/> : <Copy size={14}/>}
                        {copied ? '已复制' : '复制'}
                      </button>
                    </div>
                    <div className="p-1">
                       {!finalResult.code && (
                         <div className="h-64 flex flex-col items-center justify-center gap-4 text-slate-500">
                           <Loader2 className="animate-spin text-indigo-500" size={32}/>
                           <span className="text-sm font-mono tracking-widest opacity-50">编译中...</span>
                         </div>
                       )}
                       <ReactMarkdown components={{
                          code({node, inline, className, children, ...props}) {
                            const match = /language-(\w+)/.exec(className || '')
                            return !inline && match ? (
                              <SyntaxHighlighter
                                language={match[1]}
                                style={vscDarkPlus}
                                PreTag="div"
                                customStyle={{margin:0, padding:'2rem', background:'transparent', fontSize:'15px', lineHeight:'1.7'}}
                                {...props}
                              >
                                {String(children).replace(/\n$/, '')}
                              </SyntaxHighlighter>
                            ) : <code className="bg-slate-800 px-1 py-0.5 rounded text-orange-300 font-mono text-sm" {...props}>{children}</code>
                          }
                        }}>{finalResult.code}</ReactMarkdown>
                    </div>
                  </div>

                  {failureReport ? (
                    <motion.div initial={{opacity:0, y:20}} animate={{opacity:1, y:0}} className="rounded-2xl border border-rose-500/20 bg-rose-950/5 p-8">
                      <div className="flex items-start gap-5">
                        <div className="p-3 rounded-xl bg-rose-500/10 text-rose-400">
                          <AlertTriangle size={28} />
                        </div>
                        <div className="space-y-4 flex-1">
                          <h3 className="text-xl font-bold text-rose-200">执行异常</h3>
                          <p className="text-rose-300/70 text-base leading-relaxed">{failureReport.message}</p>
                          <div className="bg-[#0a0a0a] rounded-xl p-5 font-mono text-sm text-rose-400/80 overflow-x-auto whitespace-pre-wrap border border-rose-500/10">
                            {failureReport.issues}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ) : (
                    <div className="flex flex-col gap-12">

                      {/* 逻辑流程图 */}
                      <div className="bg-[#0f172a]/40 rounded-2xl border border-white/5 flex flex-col min-h-[500px]">
                        <div className="p-5 border-b border-white/5 flex justify-between items-center bg-[#0f172a]/60">
                          <div className="flex items-center gap-3 text-xl font-bold text-white tracking-wide">
                            <GitMerge size={22} className="text-indigo-400" /> 逻辑流程图
                          </div>
                          <button onClick={() => setShowDiagramModal(true)} className="p-2 hover:bg-white/10 rounded-lg transition text-slate-500 hover:text-white">
                            <X size={20} className="rotate-45" />
                          </button>
                        </div>
                        <div className="flex-1 p-8 flex items-center justify-center overflow-hidden">
                          {diagramCode ? (
                            <div ref={mermaidRef} className="w-full flex justify-center opacity-80 hover:opacity-100 transition-opacity" />
                          ) : (
                            <div className="flex flex-col items-center gap-4 text-slate-700">
                              {isProcessing ? <Loader2 className="animate-spin" size={32} /> : <GitMerge size={32} />}
                              <span className="text-xs font-bold tracking-widest">{isProcessing ? "渲染中..." : "等待中"}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* 深度解析 */}
                      <div className="bg-[#0f172a]/40 rounded-2xl border border-white/5 flex flex-col">
                        <div className="p-5 border-b border-white/5 flex items-center gap-3 text-xl font-bold text-white tracking-wide bg-[#0f172a]/60">
                          <BookOpen size={22} className="text-violet-400" /> 深度解析
                        </div>
                        <div className="p-8 space-y-12 flex-1">
                          {explanation ? (
                            <>
                              <div className="space-y-4">
                                <div className="flex items-center gap-2 text-emerald-400 font-bold text-lg uppercase tracking-wider">
                                  <Lightbulb size={20} /> 直觉理解
                                </div>
                                <div className="text-slate-300 pl-6 border-l-2 border-emerald-500/20">
                                  <ExplanationMarkdown content={explanation.simple} />
                                </div>
                              </div>
                              <div className="space-y-4">
                                <div className="flex items-center gap-2 text-violet-400 font-bold text-lg uppercase tracking-wider">
                                  <Layers size={20} /> 技术原理
                                </div>
                                <div className="text-slate-300 pl-6 border-l-2 border-violet-500/20">
                                  <ExplanationMarkdown content={explanation.academic} />
                                </div>
                              </div>
                            </>
                          ) : (
                            <div className="h-full flex flex-col items-center justify-center text-slate-700 gap-4">
                               {isProcessing ? <Loader2 className="animate-spin" size={32} /> : <Zap size={32} />}
                               <span className="text-xs font-bold tracking-widest">{isProcessing ? "分析中..." : "等待中"}</span>
                            </div>
                          )}
                        </div>
                      </div>

                    </div>
                  )}
                </motion.div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center space-y-8">
                   <motion.div
                     animate={{
                       color: ["#6366f1", "#a855f7", "#06b6d4", "#6366f1"],
                       textShadow: ["0 0 10px rgba(99,102,241,0.3)", "0 0 20px rgba(168,85,247,0.3)", "0 0 10px rgba(6,182,212,0.3)", "0 0 10px rgba(99,102,241,0.3)"]
                     }}
                     transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                     className="text-5xl font-black tracking-[0.2em] uppercase select-none"
                   >
                     SYSTEM READY
                   </motion.div>
                   <p className="text-slate-600 font-mono text-sm tracking-widest">Waiting for input stream...</p>
                </div>
              )}
            </div>
          </motion.div>
        ) : (
          <div className="h-full flex items-center justify-center">
             <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-5"></div>
             <div className="w-[500px] h-[500px] bg-indigo-600/5 rounded-full blur-[100px]"></div>
          </div>
        )}
      </div>

      {showDiagramModal && (
        <div className="fixed inset-0 z-[100] bg-[#020617]/95 backdrop-blur-md flex items-center justify-center p-8 animate-fade-in">
          <button
            onClick={() => setShowDiagramModal(false)}
            className="absolute top-8 right-8 p-3 bg-white/5 hover:bg-white/10 rounded-full text-white transition ring-1 ring-white/10"
          >
            <X size={28} />
          </button>
          <div className="w-full h-full max-w-[95vw] max-h-[90vh] overflow-auto flex items-center justify-center bg-[#0f172a] rounded-3xl border border-white/10 shadow-2xl">
             <div ref={mermaidModalRef} className="scale-125 origin-center p-12"></div>
          </div>
        </div>
      )}

    </div>
  );
}

export default App;