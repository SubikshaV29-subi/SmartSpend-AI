import { useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowUpRight, Bell, Camera, ChartNoAxesCombined,
  Check, ChevronDown, CircleDollarSign, Clock3, FileText, LayoutDashboard,
  LogOut, Plus, ReceiptText, ScanLine, Search, Settings2, ShieldCheck,
  Sparkles, Trash2, Wallet, X, Zap
} from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis, BarChart, Bar
} from 'recharts'
import api from './api'

const CATEGORIES = ['Groceries','Utilities','Food','Transport','Shopping','Healthcare','Entertainment','Education','Rent','Other']
const COLORS = ['#8b7cff','#43c6ac','#f6b65b','#f47f87','#64a8ff','#c18aff','#ff9b68','#77c6ed','#e5a4d8','#a7b0c2']
const money = n => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(Number(n)||0)
const todayISO = () => new Date().toISOString().slice(0,10)
const monthName = () => new Date().toLocaleDateString('en-IN',{month:'long',year:'numeric'})
const errorText = e => e?.response?.data?.error || 'Something went wrong. Please try again.'

function AuthScreen({ onAuth }) {
  const [mode,setMode] = useState('login')
  const [name,setName] = useState('')
  const [email,setEmail] = useState('')
  const [password,setPassword] = useState('')
  const [busy,setBusy] = useState(false)
  const [error,setError] = useState('')
  async function submit(e) {
    e.preventDefault(); setError(''); setBusy(true)
    try {
      const r = await api.post(`/auth/${mode}`, mode==='register'?{name,email,password}:{email,password})
      localStorage.setItem('smartspend_token',r.data.token); onAuth(r.data.user)
    } catch(err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  return <div className="auth-page"><div className="auth-art"><div className="brand"><span className="brand-icon"><Wallet size={21}/></span> SmartSpend <span className="ai-label">AI</span></div><div className="auth-copy"><span className="eyebrow"><Sparkles size={14}/> MONEY, MADE CLEAR</span><h1>Know where<br/>your money <em>goes.</em></h1><p>Scan bills. Understand habits. Make every rupee count.</p><div className="mini-preview"><div className="preview-head"><span>Monthly spending</span><strong>₹18,420</strong></div><div className="preview-bars">{[42,68,48,82,57,94,63,74,51,86,60,70].map((v,i)=><i key={i} style={{height:`${v}%`}}/>)}</div><div className="preview-foot"><span><i/> Essentials</span><span><i/> Lifestyle</span><span><i/> Savings</span></div></div></div><span className="auth-note">A clearer picture of your everyday spending.</span></div><div className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><div className="mobile-brand brand"><span className="brand-icon"><Wallet size={20}/></span> SmartSpend <span className="ai-label">AI</span></div><span className="eyebrow">{mode==='login'?'WELCOME BACK':'GET STARTED'}</span><h2>{mode==='login'?'Your money dashboard awaits.':'Build a better money habit.'}</h2><p className="muted">{mode==='login'?'Sign in to see your spending at a glance.':'Create your personal expense-tracking account.'}</p>{mode==='register'&&<label>Full name<input value={name} onChange={e=>setName(e.target.value)} placeholder="Your name" required/></label>}<label>Email address<input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com" required/></label><label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 8 characters" minLength={8} required/></label>{error&&<div className="error-msg">{error}</div>}<button className="primary-btn full-btn" disabled={busy}>{busy?'Please wait…':mode==='login'?'Sign in':'Create account'} <span>→</span></button><p className="auth-switch">{mode==='login'?"Don't have an account?":"Already have an account?"} <button type="button" onClick={()=>{setMode(mode==='login'?'register':'login');setError('')}}>{mode==='login'?'Create one':'Sign in'}</button></p><div className="secure-note"><ShieldCheck size={15}/> Your expense data is private to your account.</div></form></div></div>
}

function App() {
  const [user,setUser] = useState(null)
  const [authChecked,setAuthChecked] = useState(false)
  const [page,setPage] = useState('Overview')
  const [period,setPeriod] = useState('month')
  const [expenses,setExpenses] = useState([])
  const [analytics,setAnalytics] = useState(null)
  const [budgets,setBudgets] = useState([])
  const [loading,setLoading] = useState(false)
  const [toast,setToast] = useState('')
  const [search,setSearch] = useState('')
  const [categoryFilter,setCategoryFilter] = useState('All categories')
  const [showExpense,setShowExpense] = useState(false)
  const [editing,setEditing] = useState(null)
  const [showScan,setShowScan] = useState(false)
  const [scanFile,setScanFile] = useState(null)
  const [scanPreview,setScanPreview] = useState('')
  const [scanBusy,setScanBusy] = useState(false)
  const [scanError,setScanError] = useState('')
  const [scanResult,setScanResult] = useState(null)
  const [form,setForm] = useState({merchant:'',amount:'',category:'Other',date:todayISO(),note:''})
  const [budgetForm,setBudgetForm] = useState({category:'Groceries',monthly_limit:''})
  const [budgetBusy,setBudgetBusy] = useState(false)

  useEffect(()=>{ api.get('/auth/me').then(r=>setUser(r.data)).catch(()=>localStorage.removeItem('smartspend_token')).finally(()=>setAuthChecked(true)) },[])
  useEffect(()=>{ if(user) refresh() },[user,period])
  async function refresh() {
    setLoading(true)
    try {
      const [e,a,b] = await Promise.all([
        api.get('/expenses'), api.get('/analytics',{params:{period}}), api.get('/budgets')
      ])
      setExpenses(e.data); setAnalytics(a.data); setBudgets(b.data)
    } catch(err) { notify(errorText(err)) } finally { setLoading(false) }
  }
  function notify(message) { setToast(message); setTimeout(()=>setToast(''),3500) }
  function logout(){localStorage.removeItem('smartspend_token');setUser(null);setExpenses([]);setAnalytics(null)}
  function openNew(){setEditing(null);setForm({merchant:'',amount:'',category:'Other',date:todayISO(),note:''});setShowExpense(true)}
  function openEdit(e){setEditing(e.id);setForm({merchant:e.merchant,amount:String(e.amount),category:e.category,date:e.date,note:e.note||''});setShowExpense(true)}
  async function saveExpense(ev){
    ev.preventDefault()
    try {
      const payload={...form,amount:Number(form.amount),source:editing?'manual':(form.source||'manual')}
      if(editing) await api.put(`/expenses/${editing}`,payload); else await api.post('/expenses',payload)
      setShowExpense(false);setScanResult(null);notify(editing?'Expense updated':'Expense saved');refresh()
    } catch(err){notify(errorText(err))}
  }
  async function deleteExpense(id){
    if(!confirm('Delete this expense?')) return
    try {await api.delete(`/expenses/${id}`);notify('Expense deleted');refresh()}catch(err){notify(errorText(err))}
  }
  function openScanner(){setScanFile(null);setScanPreview('');setScanResult(null);setScanError('');setShowScan(true)}
  function chooseScan(file){
    if(!file)return
    if(!['image/jpeg','image/png','image/webp','image/bmp'].includes(file.type)){setScanError('Please choose a JPG, PNG, WEBP or BMP image.');return}
    if(file.size>8*1024*1024){setScanError('Image must be smaller than 8 MB.');return}
    setScanFile(file);setScanPreview(URL.createObjectURL(file));setScanResult(null);setScanError('')
  }
  async function scanBill(){
    if(!scanFile){setScanError('Choose a bill image first.');return}
    setScanBusy(true);setScanError('')
    try{
      const data=new FormData();data.append('file',scanFile)
      const r=await api.post('/ocr',data,{headers:{'Content-Type':'multipart/form-data'}})
      setScanResult(r.data)
    }catch(err){setScanError(errorText(err))}finally{setScanBusy(false)}
  }
  function useScanResult(){
    setForm({merchant:scanResult.merchant||'',amount:scanResult.amount==null?'':String(scanResult.amount),category:scanResult.category||'Other',date:scanResult.date||todayISO(),note:`Scanned using ${scanResult.provider||'OCR'}`,source:'ocr'})
    setEditing(null);setShowScan(false);setShowExpense(true)
  }
  async function saveBudget(e){
    e.preventDefault();setBudgetBusy(true)
    try{await api.post('/budgets',{category:budgetForm.category,monthly_limit:Number(budgetForm.monthly_limit)});setBudgetForm(v=>({...v,monthly_limit:''}));notify('Budget saved');refresh()}
    catch(err){notify(errorText(err))}finally{setBudgetBusy(false)}
  }
  async function deleteBudget(id){
    try{await api.delete(`/budgets/${id}`);notify('Budget removed');refresh()}catch(err){notify(errorText(err))}
  }
  const filteredExpenses=useMemo(()=>expenses.filter(e=>(categoryFilter==='All categories'||e.category===categoryFilter)&&`${e.merchant} ${e.category} ${e.note}`.toLowerCase().includes(search.toLowerCase())),[expenses,categoryFilter,search])
  const monthTotal=analytics?.total||0
  const thisMonthExpenses=expenses.filter(e=>e.date?.slice(0,7)===todayISO().slice(0,7))
  const currentMonthTotal=thisMonthExpenses.reduce((s,e)=>s+Number(e.amount),0)
  const topCategory=analytics?.categories?.[0]
  const maxDaily=Math.max(1,...(analytics?.daily||[]).map(d=>d.amount))
  const navItems=[{name:'Overview',icon:LayoutDashboard},{name:'Transactions',icon:ReceiptText},{name:'Scan a bill',icon:ScanLine},{name:'Budgets',icon:CircleDollarSign}]
  if(!authChecked)return <div className="loading-screen"><span className="brand-icon"><Wallet/></span><p>Preparing your money space…</p></div>
  if(!user)return <AuthScreen onAuth={setUser}/>
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-icon"><Wallet size={20}/></span> SmartSpend <span className="ai-label">AI</span></div><div className="workspace-label">WORKSPACE</div><nav>{navItems.map(item=><button key={item.name} className={`nav-item ${page===item.name?'active':''}`} onClick={()=>item.name==='Scan a bill'?openScanner():setPage(item.name)}><item.icon size={18}/><span>{item.name}</span>{item.name==='Scan a bill'&&<span className="nav-new">NEW</span>}</button>)}</nav><div className="sidebar-bottom"><div className="tip-card"><div className="tip-icon"><Sparkles size={16}/></div><strong>Small steps add up.</strong><p>Scan your next bill to keep your spending picture complete.</p><button onClick={openScanner}>Scan a bill <span>↗</span></button></div><div className="user-card"><div className="avatar">{(user.name||'U').slice(0,1).toUpperCase()}</div><div className="user-details"><strong>{user.name}</strong><span>{user.email}</span></div><button className="icon-btn logout-btn" title="Sign out" onClick={logout}><LogOut size={17}/></button></div></div></aside>
    <main className="main-content"><header className="topbar"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{page}</strong></div><div className="top-actions"><span className="today-pill"><span className="live-dot"/> {new Date().toLocaleDateString('en-IN',{weekday:'short',day:'numeric',month:'short'})}</span><button className="icon-btn notification-btn" onClick={()=>setPage('Budgets')} title="View budget alerts"><Bell size={18}/>{analytics?.alerts?.length>0&&<i/>}</button><div className="top-avatar">{(user.name||'U').slice(0,1).toUpperCase()}</div></div></header>
      {page==='Overview'&&<div className="page-wrap">
        <div className="page-heading"><div><span className="eyebrow">YOUR FINANCIAL SNAPSHOT</span><h1>Good to see you, {user.name.split(' ')[0]} <span className="wave">✳</span></h1><p>Here's what's happening with your money.</p></div><div className="heading-actions"><button className="secondary-btn" onClick={openScanner}><ScanLine size={16}/> Scan bill</button><button className="primary-btn" onClick={openNew}><Plus size={17}/> Add expense</button></div></div>
        <div className="overview-controls"><div className="period-tabs"><button className={period==='week'?'selected':''} onClick={()=>setPeriod('week')}>This week</button><button className={period==='month'?'selected':''} onClick={()=>setPeriod('month')}>This month</button></div><span className="period-label"><Clock3 size={14}/> {period==='month'?monthName():'Week to date'}</span></div>
        <div className="stats-grid">
          <StatCard title={period==='month'?'Total this month':'Total this week'} value={money(monthTotal)} icon={Wallet} tone="purple" foot={analytics?.change_percent==null?'Compared with previous period':`${Math.abs(analytics.change_percent)}% ${analytics.change_percent>=0?'up':'down'} vs previous period`} trend={analytics?.change_percent}/>
          <StatCard title="Transactions" value={analytics?.transaction_count||0} icon={ReceiptText} tone="mint" foot="Recorded in this period"/>
          <StatCard title="Average expense" value={money(analytics?.average||0)} icon={Activity} tone="amber" foot="Per transaction"/>
          <StatCard title="Top category" value={topCategory?.category||'—'} icon={ChartNoAxesCombined} tone="rose" foot={topCategory?money(topCategory.amount)+' this period':'No expenses yet'} compact/>
        </div>
        {analytics?.alerts?.length>0&&<div className="alerts-strip"><div className="alert-symbol"><Bell size={17}/></div><div className="alert-content"><strong>Budget check-in</strong><span>{analytics.alerts.map(a=>`${a.category}: ${a.percentage}% used`).join(' · ')}</span></div><button onClick={()=>setPage('Budgets')}>Review budgets <span>→</span></button></div>}
        <div className="charts-grid">
          <section className="panel spending-panel"><div className="panel-head"><div><h3>Spending trend</h3><p>Daily totals for the selected period</p></div><span className="panel-icon"><ChartNoAxesCombined size={17}/></span></div><div className="chart-total">{money(monthTotal)} <span>total</span></div><div className="area-chart">{analytics?.daily?.length?<ResponsiveContainer width="100%" height="100%"><AreaChart data={analytics.daily} margin={{top:8,right:6,left:0,bottom:0}}><defs><linearGradient id="spendGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8b7cff" stopOpacity={0.28}/><stop offset="95%" stopColor="#8b7cff" stopOpacity={0}/></linearGradient></defs><CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#252b3c"/><XAxis dataKey="date" tickFormatter={v=>new Date(v+'T00:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short'})} tick={{fill:'#8b93a8',fontSize:10}} axisLine={false} tickLine={false}/><YAxis tickFormatter={v=>v>=1000?`₹${(v/1000).toFixed(1)}k`:`₹${v}`} tick={{fill:'#8b93a8',fontSize:10}} axisLine={false} tickLine={false} width={48}/><Tooltip content={<ChartTooltip/>}/><Area type="monotone" dataKey="amount" stroke="#9b8cff" strokeWidth={2.5} fill="url(#spendGradient)" activeDot={{r:5,fill:'#9b8cff',stroke:'#fff',strokeWidth:2}}/></AreaChart></ResponsiveContainer>:<EmptyChart text="Your spending trend will appear here."/>}</div><div className="chart-legend"><span><i className="legend-purple"/> Daily spending</span><span className="chart-note">INR · {period==='month'?'Current month':'Current week'}</span></div></section>
          <section className="panel category-panel"><div className="panel-head"><div><h3>Where it goes</h3><p>Spending by category</p></div><button className="text-btn" onClick={()=>setPage('Transactions')}>Details <span>→</span></button></div><div className="donut-wrap">{analytics?.categories?.length?<><ResponsiveContainer width="100%" height={200}><PieChart><Pie data={analytics.categories} dataKey="amount" nameKey="category" innerRadius={58} outerRadius={82} paddingAngle={3} stroke="none">{analytics.categories.map((entry,i)=><Cell key={entry.category} fill={COLORS[i%COLORS.length]}/>)}</Pie><Tooltip content={<CategoryTooltip/>}/></PieChart></ResponsiveContainer><div className="donut-center"><strong>{money(monthTotal)}</strong><span>Total spent</span></div></>:<EmptyChart text="Add expenses to see category insights."/>}</div><div className="category-legend">{(analytics?.categories||[]).slice(0,5).map((c,i)=><div className="category-row" key={c.category}><span className="category-dot" style={{background:COLORS[i%COLORS.length]}}/><span className="category-name">{c.category}</span><strong>{money(c.amount)}</strong><span className="category-percent">{monthTotal?Math.round(c.amount/monthTotal*100):0}%</span></div>)}</div></section>
        </div>
        <div className="bottom-grid"><section className="panel recent-panel"><div className="panel-head"><div><h3>Recent transactions</h3><p>Your latest money movements</p></div><button className="text-btn" onClick={()=>setPage('Transactions')}>View all <span>→</span></button></div><TransactionTable expenses={expenses.slice(0,5)} onEdit={openEdit} onDelete={deleteExpense}/></section><section className="panel budget-summary"><div className="panel-head"><div><h3>Budget pulse</h3><p>Monthly category limits</p></div><button className="text-btn" onClick={()=>setPage('Budgets')}>Manage <span>→</span></button></div>{budgets.length?budgets.slice(0,4).map((b,i)=><BudgetProgress key={b.id} budget={b} color={COLORS[i%COLORS.length]}/>):<div className="empty-budget"><div className="empty-icon"><CircleDollarSign size={22}/></div><strong>Give your money a plan</strong><p>Set category budgets to get useful alerts before you overspend.</p><button className="secondary-btn" onClick={()=>setPage('Budgets')}>Set a budget <span>→</span></button></div>}</section></div>
      </div>}
      {page==='Transactions'&&<div className="page-wrap"><div className="page-heading"><div><span className="eyebrow">YOUR MONEY, ORGANIZED</span><h1>Transactions</h1><p>Search, review and manage your expenses.</p></div><div className="heading-actions"><button className="secondary-btn" onClick={openScanner}><ScanLine size={16}/> Scan bill</button><button className="primary-btn" onClick={openNew}><Plus size={17}/> Add expense</button></div></div><section className="panel transaction-page-panel"><div className="filter-bar"><div className="search-field"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search transactions…"/></div><select value={categoryFilter} onChange={e=>setCategoryFilter(e.target.value)}><option>All categories</option>{CATEGORIES.map(c=><option key={c}>{c}</option>)}</select><span className="result-count">{filteredExpenses.length} transactions</span></div><TransactionTable expenses={filteredExpenses} onEdit={openEdit} onDelete={deleteExpense}/></section></div>}
      {page==='Budgets'&&<div className="page-wrap"><div className="page-heading"><div><span className="eyebrow">SPEND WITH INTENTION</span><h1>Your budgets</h1><p>Set monthly limits and get a heads-up when you're close.</p></div></div><div className="budget-page-grid"><section className="panel budget-form-panel"><div className="panel-head"><div><h3>Create a category budget</h3><p>One limit per category, each month.</p></div><span className="panel-icon"><Settings2 size={17}/></span></div><form onSubmit={saveBudget} className="budget-form"><label>Expense category<select value={budgetForm.category} onChange={e=>setBudgetForm({...budgetForm,category:e.target.value})}>{CATEGORIES.map(c=><option key={c}>{c}</option>)}</select></label><label>Monthly limit (₹)<input type="number" min="1" step="0.01" value={budgetForm.monthly_limit} onChange={e=>setBudgetForm({...budgetForm,monthly_limit:e.target.value})} placeholder="e.g. 3000" required/></label><button className="primary-btn" disabled={budgetBusy}>{budgetBusy?'Saving…':<><Plus size={16}/> Save budget</>}</button></form><div className="budget-tip"><Sparkles size={16}/><p><strong>Quick tip</strong> Start with your most frequent categories, then adjust the limit after reviewing a full month.</p></div></section><section className="panel all-budgets-panel"><div className="panel-head"><div><h3>Monthly budget limits</h3><p>Progress updates as you save expenses.</p></div><span className="count-chip">{budgets.length} active</span></div>{budgets.length?budgets.map((b,i)=><div className="budget-item" key={b.id}><div className="budget-item-top"><span className="budget-category-icon" style={{color:COLORS[i%COLORS.length],background:COLORS[i%COLORS.length]+'1b'}}><CircleDollarSign size={18}/></span><div className="budget-item-name"><strong>{b.category}</strong><span>{money(b.spent)} spent of {money(b.monthly_limit)}</span></div><button className="icon-btn delete-budget" onClick={()=>deleteBudget(b.id)} title="Remove budget"><Trash2 size={16}/></button></div><div className="progress-track"><div className={`progress-fill ${b.percentage>=100?'danger':b.percentage>=80?'warning':''}`} style={{width:`${Math.min(b.percentage,100)}%`,background:b.percentage>=80?undefined:COLORS[i%COLORS.length]}}/></div><div className="budget-item-foot"><span>{b.percentage>=100?'Budget exceeded':b.percentage>=80?'Getting close':'Remaining'} </span><strong>{money(Math.max(0,b.monthly_limit-b.spent))}</strong></div></div>):<div className="empty-state"><CircleDollarSign size={28}/><strong>No budgets yet</strong><p>Create your first budget to start tracking category limits.</p></div>}</section></div><section className="panel alert-explainer"><div className="alert-symbol"><Bell size={19}/></div><div><h3>How SmartSpend alerts work</h3><p>At 80% of a category budget, you'll see a warning. At 100%, the app flags that budget as reached; above 100%, it shows an over-budget alert. Alerts are calculated from expenses saved for the current month.</p></div></section></div>}
      <footer className="app-footer"><span>© {new Date().getFullYear()} SmartSpend AI</span><span><ShieldCheck size={14}/> Your money data stays yours</span><span>Made for clearer money habits <span className="footer-star">✳</span></span></footer>
    </main>
    {showExpense&&<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setShowExpense(false)}}><form className="modal-card" onSubmit={saveExpense}><div className="modal-head"><div><span className="eyebrow">{editing?'UPDATE ENTRY':'KEEP TRACK'}</span><h2>{editing?'Edit expense':'Add an expense'}</h2><p>{editing?'Update the details below.':'Every little detail helps your money picture.'}</p></div><button type="button" className="icon-btn" onClick={()=>setShowExpense(false)}><X size={20}/></button></div><label>Merchant / description<input value={form.merchant} onChange={e=>setForm({...form,merchant:e.target.value})} placeholder="e.g. D-Mart, TNEB, Cafe" required/></label><div className="form-two-col"><label>Amount (₹)<input type="number" min="0.01" step="0.01" value={form.amount} onChange={e=>setForm({...form,amount:e.target.value})} placeholder="0.00" required/></label><label>Date<input type="date" value={form.date} onChange={e=>setForm({...form,date:e.target.value})} required/></label></div><label>Category<select value={form.category} onChange={e=>setForm({...form,category:e.target.value})}>{CATEGORIES.map(c=><option key={c}>{c}</option>)}</select></label><label>Note (optional)<textarea value={form.note} onChange={e=>setForm({...form,note:e.target.value})} rows="2" placeholder="Add a little context…"/></label><div className="modal-actions"><button type="button" className="secondary-btn" onClick={()=>setShowExpense(false)}>Cancel</button><button className="primary-btn"><Check size={16}/>{editing?'Save changes':'Save expense'}</button></div></form></div>}
    {showScan&&<div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setShowScan(false)}}><div className="modal-card scan-modal"><div className="modal-head"><div><span className="eyebrow">SMART SCAN</span><h2>Turn a bill into an expense.</h2><p>Upload a clear photo of a receipt or electricity bill.</p></div><button className="icon-btn" onClick={()=>setShowScan(false)}><X size={20}/></button></div><label className="upload-zone">{scanPreview?<img className="scan-preview" src={scanPreview} alt="Bill preview"/>:<><span className="upload-icon"><Camera size={25}/></span><strong>Choose a bill image</strong><span>JPG, PNG, WEBP or BMP · Up to 8 MB</span></>}<input type="file" accept="image/jpeg,image/png,image/webp,image/bmp" capture="environment" onChange={e=>chooseScan(e.target.files?.[0])}/></label>{scanFile&&<div className="selected-file"><FileText size={16}/><span>{scanFile.name}</span><button className="icon-btn" onClick={()=>{setScanFile(null);setScanPreview('');setScanResult(null)}}><X size={15}/></button></div>}{scanError&&<div className="error-msg">{scanError}</div>}{scanResult&&<div className="scan-result"><div className="scan-result-title"><Check size={17}/><div><strong>Bill text extracted</strong><span>Provider: {scanResult.provider}</span></div></div><div className="scan-fields"><div><span>Merchant</span><strong>{scanResult.merchant||'Not detected'}</strong></div><div><span>Amount</span><strong>{scanResult.amount==null?'Not detected':money(scanResult.amount)}</strong></div><div><span>Date</span><strong>{scanResult.date||'Not detected'}</strong></div><div><span>Suggested category</span><strong>{scanResult.category||'Other'}</strong></div></div><details><summary>View extracted text</summary><pre>{scanResult.raw_text}</pre></details><p className="scan-warning">Please verify these fields. OCR can misread bill dates and totals.</p></div>}<div className="modal-actions">{!scanResult?<><button className="secondary-btn" onClick={()=>setShowScan(false)}>Cancel</button><button className="primary-btn" disabled={!scanFile||scanBusy} onClick={scanBill}><ScanLine size={16}/>{scanBusy?'Reading bill…':'Extract bill details'}</button></>:<><button className="secondary-btn" onClick={()=>{setScanResult(null);setScanError('')}}>Try again</button><button className="primary-btn" onClick={useScanResult}><Check size={16}/> Review & save</button></>}</div></div></div>}
    {toast&&<div className="toast"><Check size={17}/>{toast}<button onClick={()=>setToast('')}><X size={15}/></button></div>}
  </div>
}

function StatCard({title,value,icon:Icon,tone,foot,trend,compact}) {
  return <div className="stat-card"><div className="stat-top"><span>{title}</span><span className={`stat-icon ${tone}`}><Icon size={18}/></span></div><div className={`stat-value ${compact?'compact':''}`}>{value}</div><div className="stat-foot">{trend!=null&&<span className={trend>=0?'trend-up':'trend-down'}>{trend>=0?<ArrowUpRight size={14}/>:<ArrowDownRight size={14}/>}</span>}<span>{foot}</span></div></div>
}
function ChartTooltip({active,payload,label}){if(!active||!payload?.length)return null;return <div className="chart-tooltip"><span>{label?new Date(label+'T00:00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short'}):''}</span><strong>{money(payload[0].value)}</strong></div>}
function CategoryTooltip({active,payload}){if(!active||!payload?.length)return null;return <div className="chart-tooltip"><span>{payload[0].name}</span><strong>{money(payload[0].value)}</strong></div>}
function EmptyChart({text}){return <div className="empty-chart"><div><ChartNoAxesCombined size={24}/><span>{text}</span></div></div>}
function TransactionTable({expenses,onEdit,onDelete}) {
  if(!expenses?.length)return <div className="empty-transactions"><div className="empty-icon"><ReceiptText size={23}/></div><strong>No transactions yet</strong><p>Add an expense or scan a bill to start your history.</p></div>
  return <div className="table-scroll"><table className="transactions-table"><thead><tr><th>TRANSACTION</th><th>CATEGORY</th><th>DATE</th><th>AMOUNT</th><th></th></tr></thead><tbody>{expenses.map((e,i)=><tr key={e.id}><td><div className="merchant-cell"><span className="merchant-icon" style={{color:COLORS[CATEGORIES.indexOf(e.category)%COLORS.length]}}>{e.source==='ocr'?<ScanLine size={17}/>:<ReceiptText size={17}/>}</span><div><strong>{e.merchant}</strong><span>{e.source==='ocr'?'Scanned bill':e.note||'Manual entry'}</span></div></div></td><td><span className="category-pill"><i style={{background:COLORS[Math.max(0,CATEGORIES.indexOf(e.category))%COLORS.length]}}/>{e.category}</span></td><td className="date-cell">{new Date(e.date+'T00:00:00').toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'})}</td><td className="amount-cell">{money(e.amount)}</td><td><div className="row-actions"><button className="icon-btn" title="Edit" onClick={()=>onEdit(e)}><Settings2 size={15}/></button><button className="icon-btn" title="Delete" onClick={()=>onDelete(e.id)}><Trash2 size={15}/></button></div></td></tr>)}</tbody></table></div>
}
function BudgetProgress({budget,color}){return <div className="budget-progress-item"><div className="budget-progress-head"><span>{budget.category}</span><strong>{money(budget.spent)} <small>/ {money(budget.monthly_limit)}</small></strong></div><div className="progress-track"><div className={`progress-fill ${budget.percentage>=100?'danger':budget.percentage>=80?'warning':''}`} style={{width:`${Math.min(budget.percentage,100)}%`,background:budget.percentage>=80?undefined:color}}/></div><div className="budget-progress-foot"><span>{budget.percentage>=100?'Limit reached':budget.percentage>=80?'Approaching limit':'On track'}</span><span>{budget.percentage}%</span></div></div>}
export default App
