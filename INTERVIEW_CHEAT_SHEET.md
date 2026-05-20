# AURA面试速查 v0.8.3
Agentic Unified Roleplay Assistant — TAVO与LLM的Prompt编译中间层。将混沌System Prompt拆为9区块结构化Prompt，叠加三层记忆与意图感知RAG，解决重度RP长对话15个系统性痛点。

## 关键数字墙
- **15** = LangGraph状态机节点数（7显式+6并行子任务+2条件边）
- **9** = System Prompt重组区块数（MAIN/PROTOCOL/CONSTRAINTS/CHAR/USER/STATE/RECENT/LONG/WORLD/OUTPUT）
- **3** = 记忆层级：WORKING(5轮)/RECENT(10条摘要)/LONG_TERM(RAG Top-5)
- **6** = 意图结构化字段维度（scene/action/emotion/tension/entities/pacing）
- **6** = 并行准备子任务（EntityExtract/EmotionAnalyze/MemoryRetrieve/StateManager/StyleInjection/ModelDialectCompiler）
- **2** = 质检失败最大重试次数（FormatGuard/OOCCheck/ContentFilter）
- **5** = 每5轮对话触发一次Kimi记忆总结
- **451** = IntentTagger System Prompt字符数（适配Kimi k2.6 reasoning）

## ASCII架构
```
TAVO前端 POST /v1/chat/completions → SSE流式回复
              ↓
┌─────────────────────────────────┐
│ AURA(FastAPI+LangGraph)         │
│ InputReceive→拆Prompt+解析意图    │
│              ↓                  │
│ ParallelPrep(6):EntityExtract│EmotionAnalyze│
│  MemoryRetrieve│StateManager│StyleInjection│Dialect│
│              ↓                  │
│ ContextAssemble→9区块编译+WORKING │
│              ↓                  │
│ LLMGenerate→QualityCheck(3):Format│OOC│Filter│
│  fail→回退重试(max2)              │
│              ↓pass              │
│ OutputReturn→SSE模拟器:段落切分→chunk│
│              ↓                  │
│ MemoryExtract→SQLite+FAISS存储    │
└──────────────┬──────────────────┘
               ↓
LLM后端:DeepSeek-v4-flash(主)/Kimi-k2.6(意图+总结)/Gemini-2.0-flash(预留)
```

## 数据流
TAVO→AURA(保存请求+PromptDecomposer拆解)→LLM(IntentTagger+三层记忆注入+9区块重组)→AURA(收集SSE+SQLite保存+每5轮触发总结)→TAVO(按段落切分+SSE chunk模拟流式返回)

## 技术栈
FastAPI(异步Web+SSE), LangGraph(15节点状态机+条件边回退), FAISS+SQLite(向量索引+单文件持久化), bge-small-zh-v1.5(中文轻量embedding), httpx(三后端统一调用), Pydantic v2(校验+配置)

## 高频FAQ
**Q1：AURA是什么？解决什么问题？**
TAVO发给LLM的Prompt是混沌文本块，AURA作为中间层拆解为9区块结构化Prompt，叠加RAG记忆和意图解析，解决越权输出、状态回退、记忆冗余等15个RP痛点。

**Q2：为什么加中间件，不直接调LLM？**
直接调用无法做认知心理学优化和记忆RAG召回。AURA在不修改TAVO协议前提下，把"原始透传"升级为"智能编译"。

**Q3：LangGraph 15节点怎么设计的？**
输入→并行准备→编译→生成→质检→输出→记忆固化，质检失败条件边回退(max2)。状态机让每个节点只读写AgentState，零侵入且支持断点续跑。

**Q4：项目最难的技术挑战是什么？**
Kimi k2.6的reasoning特性导致长System Prompt timeout，最终将Prompt压缩到451字符，意图场景切换kimi-k2-turbo-preview（无reasoning）才稳定。

> 打印提示：A4等宽字体(Consolas/Courier New)，9-10pt，页边距1.5cm，目标2页以内。
