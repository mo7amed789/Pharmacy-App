"""Admin-only publisher setup/review window. No keys displayed or collected."""
import json
import os
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from availability_bridge import mapping_candidates,inventory_preview
from availability_sync import Store,start_worker,KEY_ENV


def open_settings(app):
    if not app.is_admin:
        return
    path=app.db.path+'.availability.sqlite3'
    store=Store(path)
    win=tk.Toplevel(app.root);win.title('مزامنة توفر الأدوية - إعداد ومراجعة');win.geometry('980x680')
    win.transient(app.root);win.minsize(940,600)
    frame=ttk.Frame(win,padding=14);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='مزامنة التوفر منفصلة عن الكتالوج والفواتير. مقفولة افتراضياً.',font=('Segoe UI',12,'bold')).pack(anchor='e')
    ttk.Label(frame,text='لا تفعّل قبل تجهيز الموقع والفروع والمصادقة ومراجعة الربط على الطرفين. لا توجد مفاتيح في هذه الشاشة.').pack(anchor='e',pady=5)
    config=store.config();endpoint=tk.StringVar(value=config['endpoint']);branch=tk.StringVar(value=config['branch'])
    ttk.Label(frame,text='HTTPS receiver URL').pack(anchor='w');ttk.Entry(frame,textvariable=endpoint).pack(fill='x')
    ttk.Label(frame,text='Branch ID (UUID)').pack(anchor='w');ttk.Entry(frame,textvariable=branch).pack(fill='x')
    ttk.Label(frame,text='Installation ID: '+config['installation']).pack(anchor='w',pady=5)
    status=tk.StringVar();ttk.Label(frame,textvariable=status,wraplength=900).pack(anchor='w',pady=5)
    rows=ttk.Treeview(frame,columns=('id','name','pack','target','state'),show='headings',height=10)
    for key,label,width in [('id','Local ID',65),('name','Local product / strength',240),('pack','Units/box',85),('target','Platform medicine',280),('state','Review state',130)]:
        rows.heading(key,text=label);rows.column(key,width=width,minwidth=50)
    rows.pack(fill='both',expand=True)
    catalog=[];candidates=[]
    def refresh():
        c=store.config();p=store.pending()
        status.set(('ENABLED' if c['enabled'] else 'DISABLED')+' | '+c['status']+' | Reviewed: '+str(len(store.bindings()))+' | Queued: '+str(bool(p)))
    def guard(fn):
        try:fn();refresh()
        except Exception as exc:messagebox.showerror('تعذر إكمال الإعداد',str(exc),parent=win)
    def load_catalog():
        nonlocal catalog,candidates
        source=filedialog.askopenfilename(parent=win,filetypes=[('Platform catalog JSON','*.json')])
        if not source:return
        if os.path.getsize(source)>20*1024*1024:raise ValueError('Catalog too large')
        with open(source,encoding='utf-8')as f:catalog=json.load(f)
        if not isinstance(catalog,list):raise ValueError('Use an exported array of platform medicine DTOs')
        candidates=mapping_candidates(app.db,catalog);rows.delete(*rows.get_children())
        from database import units_per_box
        for i,c in enumerate(candidates):
            d=dict(app.db.conn.execute('SELECT * FROM drugs WHERE id=?',(c['externalProductId'],)).fetchone())
            rows.insert('', 'end',iid=str(i),values=(c['externalProductId'],c['name']+' / '+str(c['strength']),units_per_box(d),', '.join(c['candidateMedicineIds']),c['status']))
    def review():
        selected=rows.selection()
        if not selected:return
        candidate=candidates[int(selected[0])]
        if len(candidate['candidateMedicineIds'])!=1:raise ValueError('Exact unique box GTIN required; do not guess')
        mid=candidate['candidateMedicineIds'][0];remote=next(m for m in catalog if m['id']==mid)
        d=dict(app.db.conn.execute('SELECT * FROM drugs WHERE id=?',(candidate['externalProductId'],)).fetchone())
        from database import units_per_box
        text='Local: %s / %s / %s\nLocal units per box: %s\nPlatform: %s / %s / %s\nGTIN: %s\n\nراجع الاسم والتركيز والشكل والعبوة بالضبط على الجانبين. هل التطابق مؤكد؟\nServer binding must also be provisioned by the operator.'%(candidate['name'],candidate['strength'],candidate['dosageForm'],units_per_box(d),remote.get('brandName',''),remote.get('strength',''),remote.get('dosageForm',''),', '.join(candidate['boxGtins']))
        if not messagebox.askyesno('مراجعة عبوة واحدة',text,parent=win):return
        store.review(app.db,catalog,candidate['externalProductId'],mid)
        rows.set(selected[0],'state','reviewed locally')
    def export():
        store.configure(endpoint.get().strip(),branch.get().strip(),False)
        target=filedialog.asksaveasfilename(parent=win,defaultextension='.json',filetypes=[('Reviewed binding manifest','*.json')])
        if target:
            with open(target,'w',encoding='utf-8')as f:json.dump(store.provision_manifest(),f,indent=2,ensure_ascii=False)
    def preview():
        p=inventory_preview(app.db,store.bindings())
        if p['held']:raise ValueError('Held mappings: '+str(len(p['held']))+'. Review changed identity or prices before enabling.')
        messagebox.showinfo('معاينة محلية فقط','Reviewed items: %s\nExplicit zero: %s\nNo stock transmitted.'%(len(p['items']),sum(i['availableQuantity']==0 for i in p['items'])),parent=win)
    def disable():
        store.disable()
        event=getattr(app,'_availability_stop',None)
        if event:event.set()
    def enable():
        if not store.bindings():raise ValueError('Review mappings and provision them on the server first')
        if not messagebox.askyesno('تشغيل لاحق فقط','هل جهزت الفرع والمكان والمصادقة والربط المراجع على السيرفر؟\nسيتم إرسال المخزون والأسعار للمنتجات المراجعة كل دقيقة.\nمفتاح الناشر مطلوب في متغير البيئة '+KEY_ENV,parent=win):return
        store.configure(endpoint.get().strip(),branch.get().strip(),True)
        event=getattr(app,'_availability_stop',None)
        if event:event.set()
        def restart_when_released():
            if event and event.thread.is_alive():
                app.root.after(250,restart_when_released)
            else:
                app._availability_stop=start_worker(app.db.path,path)
        restart_when_released()
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=10)
    for text,fn in [('تحميل كتالوج الموقع JSON',load_catalog),('مراجعة المحدد',review),('معاينة فقط',preview),('حفظ وتصدير الربط',export),('إيقاف',disable),('تفعيل بعد التجهيز',enable)]:
        ttk.Button(buttons,text=text,command=lambda f=fn:guard(f)).pack(side='left',padx=3)
    def close():store.close();win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);refresh()
    return win
