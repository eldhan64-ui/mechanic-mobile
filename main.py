import os, sqlite3, uuid, json, shutil, mimetypes, base64, urllib.request, urllib.error, urllib.parse
from datetime import datetime

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
try:
    from android.storage import primary_external_storage_path
    from android.permissions import request_permissions, Permission
except Exception:
    primary_external_storage_path = None
    request_permissions = None
    Permission = None

try:
    from plyer import camera, filechooser
except Exception:
    camera = None
    filechooser = None

APP_NAME = 'Mechanic Mobile'
APP_DIR = os.path.join(App.get_running_app().user_data_dir if App.get_running_app() else os.path.expanduser('~'), 'mechanic_mobile')
DB = os.path.join(APP_DIR, 'mechanic_mobile.db')
FILES_DIR = os.path.join(APP_DIR, 'files')

def public_base():
    try:
        base = primary_external_storage_path() if primary_external_storage_path else '/sdcard'
    except Exception:
        base = '/sdcard'
    return base
PUBLIC_BASE = public_base()
PICTURES_DIR = os.path.join(PUBLIC_BASE, 'Pictures', 'Mechanic')
DOCUMENTS_DIR = os.path.join(PUBLIC_BASE, 'Documents', 'Mechanic')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS equipment (
 id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, inventory_no TEXT UNIQUE NOT NULL,
 name TEXT, brand_model TEXT, purchase_date TEXT, designation TEXT, condition TEXT, notes TEXT,
 updated_at TEXT NOT NULL, sync_base_at TEXT DEFAULT '', dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS materials (
 id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, name TEXT, purchase_date TEXT, number TEXT,
 purpose TEXT, weight TEXT, notes TEXT, balance REAL DEFAULT 0, quantity REAL DEFAULT 0,
 updated_at TEXT NOT NULL, sync_base_at TEXT DEFAULT '', dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS repairs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, equipment_uid TEXT, equipment_name TEXT,
 repair_date TEXT, equipment_inventory_no TEXT, cost REAL DEFAULT 0, problem TEXT, work_done TEXT, materials_used TEXT, notes TEXT,
 updated_at TEXT NOT NULL, sync_base_at TEXT DEFAULT '', dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS files (
 id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT UNIQUE NOT NULL, owner_type TEXT, owner_uid TEXT,
 path TEXT, name TEXT, file_type TEXT, updated_at TEXT NOT NULL, dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS device_info (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sync_log (id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT, started_at TEXT, finished_at TEXT, status TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS sync_conflicts (id INTEGER PRIMARY KEY AUTOINCREMENT, table_name TEXT, uid TEXT, client_json TEXT, server_json TEXT, created_at TEXT, resolved INTEGER DEFAULT 0);
'''


def now(): return datetime.now().isoformat(timespec='seconds')

def db_connect():
    os.makedirs(APP_DIR, exist_ok=True); os.makedirs(FILES_DIR, exist_ok=True)
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; c.executescript(SCHEMA); return c

def migrate_sync_columns(db):
    for t in ('equipment','materials','repairs'):
        cols=[r['name'] for r in db.execute(f'PRAGMA table_info({t})')]
        if 'sync_base_at' not in cols:
            db.execute(f"ALTER TABLE {t} ADD COLUMN sync_base_at TEXT DEFAULT ''")
    db.commit()

def safe_float(v):
    try: return float(str(v).replace(',', '.'))
    except Exception: return 0.0

def next_inventory(c):
    nums=[]
    for r in c.execute("SELECT inventory_no FROM equipment WHERE inventory_no LIKE 'AV-%'"):
        try: nums.append(int(r['inventory_no'].split('-')[-1]))
        except Exception: pass
    return f"AV-{(max(nums)+1 if nums else 1):04d}"

class MechanicMobile(App):
    title = APP_NAME

    def build(self):
        if request_permissions and Permission:
            try: request_permissions([Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])
            except Exception: pass
        os.makedirs(PICTURES_DIR, exist_ok=True); os.makedirs(DOCUMENTS_DIR, exist_ok=True)
        self.db = db_connect()
        migrate_sync_columns(self.db)
        self.ensure_device()
        self.migrate_bundled_db()
        root = TabbedPanel(do_default_tab=False, tab_width=dp(135))
        for title, builder in [('AVADANLIQ', self.equipment_tab), ('TƏMİR', self.repairs_tab), ('MATERİALLAR', self.materials_tab), ('SİNXRONİZASİYA', self.sync_tab)]:
            t=TabbedPanelItem(text=title); t.add_widget(builder()); root.add_widget(t)
        return root

    def ensure_device(self):
        if not self.db.execute("SELECT 1 FROM device_info WHERE key='device_id'").fetchone():
            self.db.execute("INSERT INTO device_info VALUES('device_id',?)", (str(uuid.uuid4()),)); self.db.commit()

    def migrate_bundled_db(self):
        if self.db.execute('SELECT COUNT(*) FROM equipment').fetchone()[0] > 0: return
        candidates = [
            os.path.join(os.path.dirname(__file__), 'mechanic.db'),
            os.path.join(os.path.dirname(__file__), 'data', 'mechanic.db'),
        ]
        src = next((p for p in candidates if os.path.exists(p)), None)
        if not src: return
        try:
            old=sqlite3.connect(src); old.row_factory=sqlite3.Row
            for r in old.execute('SELECT * FROM equipment'):
                self.db.execute('INSERT OR IGNORE INTO equipment(uid,inventory_no,name,brand_model,purchase_date,designation,condition,notes,updated_at,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,0)',
                    (str(uuid.uuid4()), r['inventory_no'] or next_inventory(self.db), r['name'], r['nomenclature'] or '', r['purchase_date'] or '', r['designation'] or '', r['condition'] or 'İşlək', r['notes'] or '', now()))
            for r in old.execute('SELECT * FROM materials'):
                self.db.execute('INSERT OR IGNORE INTO materials(uid,name,purchase_date,number,purpose,weight,notes,balance,quantity,updated_at,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,0)',
                    (str(uuid.uuid4()), r['name'], r['purchase_date'] or '', r['number'] or '', r['condition'] or '', r['weight'] or '', r['notes'] or '', r['balance'] or 0, r['quantity'] or 0, now()))
            for r in old.execute('SELECT * FROM repairs'):
                self.db.execute('INSERT OR IGNORE INTO repairs(uid,equipment_uid,equipment_name,repair_date,equipment_inventory_no,cost,problem,work_done,materials_used,notes,updated_at,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)',
                    (str(uuid.uuid4()), '', r['equipment_name'] or r['name'] or '', r['time'] or '', r['equipment_inventory_no'] or '', r['cost'] or 0, r['problem'] or '', r['work_done'] or '', r['materials_used'] or '', r['notes'] or '', now()))
            self.db.commit(); old.close()
        except Exception:
            self.db.rollback()

    def make_form(self, fields):
        box=GridLayout(cols=2, spacing=dp(6), padding=dp(10), size_hint_y=None); box.bind(minimum_height=box.setter('height')); widgets=[]
        for key,label,default in fields:
            box.add_widget(Label(text=label, size_hint_y=None, height=dp(42)))
            w=TextInput(text=str(default if default is not None else ''), multiline=False, size_hint_y=None, height=dp(42))
            widgets.append((key,w)); box.add_widget(w)
        # Enter: next field, last field does not save automatically; explicit save is safer on touch devices.
        for i,(_,w) in enumerate(widgets):
            nxt = widgets[i+1][1] if i+1 < len(widgets) else None
            w.bind(on_text_validate=lambda inst, n=nxt: n.focus() if n else None)
        return box, dict(widgets)

    def popup(self,title,content,save=None,extra=None):
        outer=BoxLayout(orientation='vertical')
        scroll=ScrollView(); scroll.add_widget(content); outer.add_widget(scroll)
        buttons=BoxLayout(size_hint_y=None,height=dp(52),spacing=dp(6),padding=dp(4))
        if save:
            b=Button(text='Saxla'); b.bind(on_release=lambda *_: (save(),p.dismiss())); buttons.add_widget(b)
        if extra:
            for text,fn in extra:
                b=Button(text=text); b.bind(on_release=lambda _,f=fn:f()); buttons.add_widget(b)
        c=Button(text='Ləğv et'); c.bind(on_release=lambda *_: p.dismiss()); buttons.add_widget(c); outer.add_widget(buttons)
        p=Popup(title=title,content=outer,size_hint=(.96,.92)); p.open(); return p

    # ---------- Equipment ----------
    def equipment_tab(self):
        root=BoxLayout(orientation='vertical',padding=dp(8),spacing=dp(6))
        top=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(6))
        self.eq_search=TextInput(hint_text='Avadanlıq axtar...',multiline=False,size_hint_x=1)
        self.eq_search.bind(text=lambda *_: self.refresh_equipment())
        top.add_widget(self.eq_search)
        add=Button(text='+ Yeni avadanlıq',size_hint_x=None,width=dp(145)); add.bind(on_release=lambda *_: self.add_equipment()); top.add_widget(add); root.add_widget(top)
        self.eq_list=BoxLayout(orientation='vertical',size_hint_y=None,spacing=dp(4)); self.eq_list.bind(minimum_height=self.eq_list.setter('height')); s=ScrollView(); s.add_widget(self.eq_list); root.add_widget(s); self.refresh_equipment(); return root
    def refresh_equipment(self):
        if not hasattr(self,'eq_list'): return
        self.eq_list.clear_widgets()
        q=(self.eq_search.text if hasattr(self,'eq_search') else '').strip().lower()
        for r in self.db.execute('SELECT * FROM equipment ORDER BY inventory_no'):
            text=f"{r['inventory_no']} | {r['name']} | {r['brand_model']} | {r['condition']}"
            if q and q not in text.lower(): continue
            row=BoxLayout(size_hint_y=None,height=dp(64),spacing=dp(4))
            imgs=self.db.execute("SELECT path FROM files WHERE owner_type='equipment' AND owner_uid=? AND file_type LIKE 'image/%' ORDER BY updated_at DESC LIMIT 1",(r['uid'],)).fetchone()
            if imgs and os.path.exists(imgs['path']):
                row.add_widget(Image(source=imgs['path'],size_hint_x=None,width=dp(60),allow_stretch=True,keep_ratio=True))
            b=Button(text=text); b.bind(on_release=lambda _,rr=r:self.edit_equipment(rr)); row.add_widget(b)
            h=Button(text='Təmir',size_hint_x=None,width=dp(72)); h.bind(on_release=lambda _,rr=r:self.show_repair_history(rr['uid'],rr['inventory_no'])); row.add_widget(h)
            self.eq_list.add_widget(row)
    def add_equipment(self):
        inv=next_inventory(self.db); fields=[('name','Avadanlığın adı',''),('brand_model','Marka + Model',''),('purchase_date','Alınma tarixi',''),('designation','Təyinatı',''),('condition','Vəziyyəti','İşlək'),('notes','Qeyd','')]; content,w=self.make_form(fields)
        def save():
            self.db.execute('INSERT INTO equipment(uid,inventory_no,name,brand_model,purchase_date,designation,condition,notes,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),inv,*[w[k].text for k,_,_ in fields],now())); self.db.commit(); self.refresh_equipment()
        self.popup('Yeni avadanlıq',content,save, [('📷 Foto', lambda:self.capture_for('equipment', self._selected_new_uid('equipment',inv)))])
    def _selected_new_uid(self, typ, inv):
        r=self.db.execute('SELECT uid FROM equipment WHERE inventory_no=?', (inv,)).fetchone() if typ=='equipment' else None
        return r['uid'] if r else ''
    def edit_equipment(self,r):
        fields=[('name','Avadanlığın adı',r['name']),('brand_model','Marka + Model',r['brand_model']),('purchase_date','Alınma tarixi',r['purchase_date']),('designation','Təyinatı',r['designation']),('condition','Vəziyyəti',r['condition']),('notes','Qeyd',r['notes'])]; content,w=self.make_form(fields)
        def save(): self.db.execute('UPDATE equipment SET name=?,brand_model=?,purchase_date=?,designation=?,condition=?,notes=?,updated_at=?,dirty=1 WHERE id=?',(*[w[k].text for k,_,_ in fields],now(),r['id'])); self.db.commit(); self.refresh_equipment()
        self.popup(f"Redaktə — {r['inventory_no']}",content,save,[('📷 Foto',lambda:self.capture_for('equipment',r['uid'])),('📎 Fayl',lambda:self.pick_file_for('equipment',r['uid'])),('📂 Fayllar',lambda:self.show_files('equipment',r['uid'],f"Fayllar — {r['inventory_no']}"))])

    # ---------- Repairs ----------
    def repairs_tab(self):
        root=BoxLayout(orientation='vertical',padding=dp(8),spacing=dp(6)); top=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(6))
        self.rep_search=TextInput(hint_text='Təmir axtar...',multiline=False); self.rep_search.bind(text=lambda *_: self.refresh_repairs()); top.add_widget(self.rep_search)
        b=Button(text='+ Yeni təmir',size_hint_x=None,width=dp(130)); b.bind(on_release=lambda *_: self.add_repair()); top.add_widget(b); root.add_widget(top); self.rep_list=BoxLayout(orientation='vertical',size_hint_y=None); self.rep_list.bind(minimum_height=self.rep_list.setter('height')); s=ScrollView(); s.add_widget(self.rep_list); root.add_widget(s); self.refresh_repairs(); return root
    def refresh_repairs(self):
        if not hasattr(self,'rep_list'): return
        self.rep_list.clear_widgets()
        q=(self.rep_search.text if hasattr(self,'rep_search') else '').strip().lower()
        for r in self.db.execute('SELECT * FROM repairs ORDER BY repair_date DESC'):
            text=f"{r['repair_date']} | {r['equipment_name']} | {r['problem']}"
            if q and q not in text.lower(): continue
            b=Button(text=text,size_hint_y=None,height=dp(52)); b.bind(on_release=lambda _,rr=r:self.edit_repair(rr)); self.rep_list.add_widget(b)
    def add_repair(self):
        eq=self.db.execute('SELECT * FROM equipment ORDER BY inventory_no').fetchall(); names=[f"{r['inventory_no']} | {r['name']}" for r in eq] or ['']
        box=GridLayout(cols=2,spacing=dp(6),padding=dp(10),size_hint_y=None); box.bind(minimum_height=box.setter('height'))
        box.add_widget(Label(text='Avadanlıq',size_hint_y=None,height=dp(42))); sp=Spinner(text=names[0],values=names,size_hint_y=None,height=dp(42)); box.add_widget(sp)
        ws={}
        for k,l in [('repair_date','Tarix'),('problem','Nasazlıq'),('work_done','Görülən iş'),('materials_used','İşlənən materiallar'),('cost','Xərc'),('notes','Qeyd')]:
            box.add_widget(Label(text=l,size_hint_y=None,height=dp(42))); w=TextInput(multiline=False,size_hint_y=None,height=dp(42)); ws[k]=w; box.add_widget(w)
        def save():
            er=eq[names.index(sp.text)] if eq and sp.text in names else None
            self.db.execute('INSERT INTO repairs(uid,equipment_uid,equipment_name,repair_date,equipment_inventory_no,cost,problem,work_done,materials_used,notes,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),er['uid'] if er else '',er['name'] if er else sp.text,ws['repair_date'].text,er['inventory_no'] if er else '',safe_float(ws['cost'].text),ws['problem'].text,ws['work_done'].text,ws['materials_used'].text,ws['notes'].text,now())); self.db.commit(); self.refresh_repairs()
        self.popup('Yeni təmir',box,save)
    def edit_repair(self,r):
        fields=[('equipment_inventory_no','İnventar №',r['equipment_inventory_no']),('repair_date','Tarix',r['repair_date']),('problem','Nasazlıq',r['problem']),('work_done','Görülən iş',r['work_done']),('materials_used','İşlənən materiallar',r['materials_used']),('cost','Xərc',r['cost']),('notes','Qeyd',r['notes'])]; content,w=self.make_form(fields)
        def save():
            self.db.execute('UPDATE repairs SET equipment_inventory_no=?,repair_date=?,problem=?,work_done=?,materials_used=?,cost=?,notes=?,updated_at=?,dirty=1 WHERE id=?',(w['equipment_inventory_no'].text,w['repair_date'].text,w['problem'].text,w['work_done'].text,w['materials_used'].text,safe_float(w['cost'].text),w['notes'].text,now(),r['id']))
            self.db.commit(); self.refresh_repairs()
        self.popup('Təmirə düzəliş',content,save,[('📷 Foto',lambda:self.capture_for('repair',r['uid'])),('📎 Fayl',lambda:self.pick_file_for('repair',r['uid'])),('📂 Fayllar',lambda:self.show_files('repair',r['uid'],'Təmir faylları'))])

    def show_repair_history(self, equipment_uid, inventory_no):
        rows=self.db.execute('SELECT repair_date,problem,work_done,cost FROM repairs WHERE equipment_uid=? OR equipment_inventory_no=? ORDER BY repair_date DESC',(equipment_uid,inventory_no)).fetchall()
        box=BoxLayout(orientation='vertical',padding=dp(8),spacing=dp(5))
        scroll=ScrollView(); items=BoxLayout(orientation='vertical',size_hint_y=None,spacing=dp(4)); items.bind(minimum_height=items.setter('height'))
        if not rows:
            items.add_widget(Label(text='Bu avadanlıq üçün təmir qeydi yoxdur.',size_hint_y=None,height=dp(45)))
        else:
            for r in rows:
                txt=f"{r['repair_date']} | {r['problem']}\n{r['work_done']} | Xərc: {r['cost']}"
                items.add_widget(Label(text=txt,size_hint_y=None,height=dp(70)))
        scroll.add_widget(items); box.add_widget(scroll)
        close=Button(text='Bağla',size_hint_y=None,height=dp(48)); box.add_widget(close)
        pop=Popup(title=f'Təmir tarixçəsi — {inventory_no}',content=box,size_hint=(.96,.85)); close.bind(on_release=pop.dismiss); pop.open()

    # ---------- Materials ----------
    def materials_tab(self):
        root=BoxLayout(orientation='vertical',padding=dp(8)); b=Button(text='+ Yeni material',size_hint_y=None,height=dp(48)); b.bind(on_release=lambda *_: self.add_material()); root.add_widget(b); self.mat_list=BoxLayout(orientation='vertical',size_hint_y=None); self.mat_list.bind(minimum_height=self.mat_list.setter('height')); s=ScrollView(); s.add_widget(self.mat_list); root.add_widget(s); self.refresh_materials(); return root
    def refresh_materials(self):
        if not hasattr(self,'mat_list'): return
        self.mat_list.clear_widgets()
        for r in self.db.execute('SELECT * FROM materials ORDER BY name'):
            b=Button(text=f"{r['name']} | Qalıq: {r['balance']}",size_hint_y=None,height=dp(52)); b.bind(on_release=lambda _,rr=r:self.edit_material(rr)); self.mat_list.add_widget(b)
    def add_material(self):
        fields=[('name','Ad',''),('purchase_date','Alış tarixi',''),('number','Nömrə',''),('purpose','Təyinatı',''),('weight','Kütlə',''),('notes','Qeyd',''),('balance','Qalıq','0')]; content,w=self.make_form(fields)
        def save():
            bal=safe_float(w['balance'].text); self.db.execute('INSERT INTO materials(uid,name,purchase_date,number,purpose,weight,notes,balance,quantity,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),*[w[k].text for k,_,_ in fields[:-1]],bal,bal,now())); self.db.commit(); self.refresh_materials()
        self.popup('Yeni material',content,save)
    def edit_material(self,r):
        fields=[('name','Ad',r['name']),('purchase_date','Alış tarixi',r['purchase_date']),('number','Nömrə',r['number']),('purpose','Təyinatı',r['purpose']),('weight','Kütlə',r['weight']),('notes','Qeyd',r['notes']),('balance','Qalıq',r['balance'])]; content,w=self.make_form(fields)
        def save():
            bal=safe_float(w['balance'].text); self.db.execute('UPDATE materials SET name=?,purchase_date=?,number=?,purpose=?,weight=?,notes=?,balance=?,quantity=?,updated_at=?,dirty=1 WHERE id=?',(*[w[k].text for k,_,_ in fields[:-1]],bal,bal,now(),r['id'])); self.db.commit(); self.refresh_materials()
        self.popup('Materiala düzəliş',content,save,[('📎 Fayl',lambda:self.pick_file_for('material',r['uid'])),('📂 Fayllar',lambda:self.show_files('material',r['uid'],'Material faylları'))])

    def show_files(self, owner_type, owner_uid, title=None):
        rows=self.db.execute('SELECT * FROM files WHERE owner_type=? AND owner_uid=? ORDER BY updated_at DESC', (owner_type, owner_uid)).fetchall()
        outer=BoxLayout(orientation='vertical',padding=dp(8),spacing=dp(6))
        scroll=ScrollView(); items=BoxLayout(orientation='vertical',size_hint_y=None,spacing=dp(6)); items.bind(minimum_height=items.setter('height'))
        if not rows:
            items.add_widget(Label(text='Bu qeydə əlavə edilmiş fayl yoxdur.',size_hint_y=None,height=dp(45)))
        for r in rows:
            row=BoxLayout(size_hint_y=None,height=dp(72),spacing=dp(6))
            if (r['file_type'] or '').startswith('image/') and os.path.exists(r['path']):
                im=Image(source=r['path'],size_hint_x=None,width=dp(64),allow_stretch=True,keep_ratio=True)
                row.add_widget(im)
            info=Label(text=f"{r['name']}\n{r['file_type'] or 'fayl'}",halign='left',valign='middle')
            row.add_widget(info)
            openb=Button(text='Aç',size_hint_x=None,width=dp(60))
            openb.bind(on_release=lambda _, path=r['path']: self.open_file(path))
            row.add_widget(openb)
            items.add_widget(row)
        scroll.add_widget(items); outer.add_widget(scroll)
        close=Button(text='Bağla',size_hint_y=None,height=dp(48)); outer.add_widget(close)
        pop=Popup(title=title or 'Fayllar',content=outer,size_hint=(.96,.88)); close.bind(on_release=pop.dismiss); pop.open()

    def open_file(self,path):
        if not os.path.exists(path):
            self.info('Fayl tapılmadı: '+path,'Fayl')
            return
        try:
            from plyer import filechooser as _fc
            # Android-də faylı xarici tətbiqdə açmaq üçün intent lazımdır; burada yolu göstəririk.
            self.info(path,'Faylın yeri')
        except Exception:
            self.info(path,'Faylın yeri')

    # ---------- Camera / files ----------
    def owner_dir(self, owner_type, owner_uid, kind='documents'):
        base = PICTURES_DIR if kind == 'pictures' else DOCUMENTS_DIR
        d=os.path.join(base,owner_type,owner_uid); os.makedirs(d,exist_ok=True); return d
    def capture_for(self, owner_type, owner_uid):
        if not owner_uid:
            self.info('Əvvəlcə qeydi yadda saxlayın.','Foto')
            return
        if camera is None:
            self.info('Kamera modulu əlçatan deyil.','Xəta'); return
        d=self.owner_dir(owner_type,owner_uid,'pictures'); path=os.path.join(d,f"foto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        try:
            camera.take_picture(filename=path,on_complete=lambda p:self.register_file(owner_type,owner_uid,p))
        except Exception as e: self.info(str(e),'Kamera xətası')
    def pick_file_for(self, owner_type, owner_uid):
        if not owner_uid:
            self.info('Əvvəlcə qeydi yadda saxlayın.','Fayl'); return
        if filechooser is None:
            self.info('Fayl seçici əlçatan deyil.','Xəta'); return
        try:
            filechooser.open_file(on_selection=lambda sel:self.on_file_selected(owner_type,owner_uid,sel))
        except Exception as e: self.info(str(e),'Fayl xətası')
    def on_file_selected(self,owner_type,owner_uid,selection):
        if not selection: return
        src=selection[0]; d=self.owner_dir(owner_type,owner_uid); name=os.path.basename(src); dst=os.path.join(d,name)
        try:
            if os.path.abspath(src)!=os.path.abspath(dst): shutil.copy2(src,dst)
            self.register_file(owner_type,owner_uid,dst)
        except Exception as e: self.info(str(e),'Fayl köçürülmədi')
    def register_file(self,owner_type,owner_uid,path):
        name=os.path.basename(path); typ=mimetypes.guess_type(name)[0] or 'application/octet-stream'
        self.db.execute('INSERT INTO files(uid,owner_type,owner_uid,path,name,file_type,updated_at,dirty) VALUES(?,?,?,?,?,?,?,1)',(str(uuid.uuid4()),owner_type,owner_uid,path,name,typ,now())); self.db.commit(); self.info(f'Əlavə edildi: {name}','Uğurlu')

    def register_pulled_file(self,f):
        owner_type=f.get('owner_type','other'); owner_uid=f.get('owner_uid',''); name=os.path.basename(f.get('name','file.bin'))
        if not owner_uid: return
        d=self.owner_dir(owner_type,owner_uid); path=os.path.join(d,name)
        try:
            raw=base64.b64decode(f.get('data','')); open(path,'wb').write(raw)
            old=self.db.execute('SELECT uid FROM files WHERE uid=?',(f.get('uid',''),)).fetchone()
            if old: self.db.execute('UPDATE files SET path=?,name=?,file_type=?,updated_at=?,dirty=0 WHERE uid=?',(path,name,f.get('file_type',''),f.get('updated_at') or now(),f.get('uid')))
            else: self.db.execute('INSERT INTO files(uid,owner_type,owner_uid,path,name,file_type,updated_at,dirty) VALUES(?,?,?,?,?,?,?,0)',(f.get('uid') or str(uuid.uuid4()),owner_type,owner_uid,path,name,f.get('file_type',''),f.get('updated_at') or now()))
        except Exception: pass
    def info(self,text,title='Məlumat'):
        Popup(title=title,content=Label(text=text),size_hint=(.85,.3)).open()

    # ---------- Wi-Fi Sync ----------
    def sync_tab(self):
        box=BoxLayout(orientation='vertical',padding=dp(15),spacing=dp(10))
        box.add_widget(Label(text='Windows kompüterinin Wi-Fi ünvanını yazın. Məsələn: http://192.168.1.10:8765',size_hint_y=None,height=dp(55)))
        self.sync_url=TextInput(text=self.db.execute("SELECT value FROM device_info WHERE key='server_url'").fetchone()['value'] if self.db.execute("SELECT value FROM device_info WHERE key='server_url'").fetchone() else 'http://192.168.1.10:8765',multiline=False,size_hint_y=None,height=dp(48))
        box.add_widget(self.sync_url)
        row=BoxLayout(size_hint_y=None,height=dp(52),spacing=dp(6))
        t=Button(text='Bağlantını yoxla'); t.bind(on_release=lambda *_:self.test_sync()); row.add_widget(t)
        b=Button(text='SİNXRONLAŞDIR'); b.bind(on_release=lambda *_:self.perform_sync()); row.add_widget(b); box.add_widget(row)
        self.sync_label=Label(text=''); box.add_widget(self.sync_label)
        self.sync_status_widget=Button(text='Gözləyən dəyişiklikləri göstər',size_hint_y=None,height=dp(50)); self.sync_status_widget.bind(on_release=lambda *_:self.sync_status()); box.add_widget(self.sync_status_widget)
        self.conflict_widget=Button(text='⚠ Toqquşmaları göstər',size_hint_y=None,height=dp(50)); self.conflict_widget.bind(on_release=lambda *_:self.show_conflicts()); box.add_widget(self.conflict_widget)
        return box

    def server_url(self):
        u=self.sync_url.text.strip().rstrip('/')
        if not u.startswith('http://') and not u.startswith('https://'): u='http://'+u
        self.db.execute("INSERT OR REPLACE INTO device_info(key,value) VALUES('server_url',?)",(u,)); self.db.commit(); return u

    def http_json(self, method, url, payload=None, timeout=8):
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8') if payload is not None else None
        req=urllib.request.Request(url,data=data,method=method,headers={'Content-Type':'application/json; charset=utf-8','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=timeout) as r: return json.loads(r.read().decode('utf-8'))

    def test_sync(self):
        try:
            res=self.http_json('GET',self.server_url()+'/hello')
            self.sync_label.text=f"Bağlantı OK — {res.get('server','Windows')}"
        except Exception as e:
            self.sync_label.text='Bağlantı alınmadı: '+str(e)

    def build_sync_payload(self):
        dev=self.db.execute("SELECT value FROM device_info WHERE key='device_id'").fetchone()['value']
        payload={'device_id':dev,'device_name':'Android planşet','equipment':[],'materials':[],'repairs':[],'files':[]}
        for typ in ('equipment','materials','repairs'):
            for r in self.db.execute(f'SELECT * FROM {typ} WHERE dirty=1'):
                d=dict(r); d.pop('free_text',None); d['base_updated_at']=d.get('sync_base_at','') or ''; payload[typ].append(d)
        for r in self.db.execute('SELECT * FROM files WHERE dirty=1'):
            try:
                with open(r['path'],'rb') as f: raw=base64.b64encode(f.read()).decode('ascii')
                payload['files'].append({'uid':r['uid'],'owner_type':r['owner_type'],'owner_uid':r['owner_uid'],'name':r['name'],'file_type':r['file_type'],'data':raw})
            except Exception: pass
        return payload

    def save_conflict(self, typ, uid, client, server):
        self.db.execute('INSERT INTO sync_conflicts(table_name,uid,client_json,server_json,created_at,resolved) VALUES(?,?,?,?,?,0)',(typ,uid,json.dumps(client,ensure_ascii=False),json.dumps(server,ensure_ascii=False),now()))

    def apply_server_changes(self, changes):
        conflicts=0
        for item in changes or []:
            typ=item.get('table'); d=item.get('data') or {}; uid=d.get('uid')
            if typ not in ('equipment','materials','repairs') or not uid: continue
            local=self.db.execute(f'SELECT * FROM {typ} WHERE uid=?',(uid,)).fetchone()
            if local and local['dirty'] and (local['updated_at'] or '') != (d.get('updated_at','') or ''):
                self.save_conflict(typ,uid,dict(local),d); conflicts+=1; continue
            if typ=='equipment':
                row=local
                vals=(d.get('inventory_no',''),d.get('name',''),d.get('nomenclature',d.get('brand_model','')),d.get('purchase_date',''),d.get('designation',''),d.get('condition','İşlək'),d.get('notes',''),d.get('updated_at',now()),d.get('updated_at',now()),uid)
                if row: self.db.execute('UPDATE equipment SET inventory_no=?,name=?,brand_model=?,purchase_date=?,designation=?,condition=?,notes=?,updated_at=?,sync_base_at=?,dirty=0 WHERE uid=?',vals)
                else: self.db.execute('INSERT INTO equipment(uid,inventory_no,name,brand_model,purchase_date,designation,condition,notes,updated_at,sync_base_at,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,0)',(uid,)+vals[:-1])
            elif typ=='materials':
                vals=(d.get('name',''),d.get('purchase_date',''),d.get('number',''),d.get('condition',d.get('purpose','')),d.get('weight',''),d.get('notes',''),d.get('balance',0),d.get('quantity',d.get('balance',0)),d.get('updated_at',now()),d.get('updated_at',now()),uid)
                if local: self.db.execute('UPDATE materials SET name=?,purchase_date=?,number=?,purpose=?,weight=?,notes=?,balance=?,quantity=?,updated_at=?,sync_base_at=?,dirty=0 WHERE uid=?',vals)
                else: self.db.execute('INSERT INTO materials(uid,name,purchase_date,number,purpose,weight,notes,balance,quantity,updated_at,sync_base_at,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)',(uid,)+vals[:-1])
            else:
                vals=(d.get('equipment_name',d.get('name','')),d.get('time',d.get('repair_date','')),d.get('cost',0),d.get('materials_used',''),d.get('notes',''),d.get('equipment_name',''),d.get('problem',''),d.get('work_done',''),d.get('updated_at',now()),d.get('updated_at',now()),uid)
                if local: self.db.execute('UPDATE repairs SET equipment_name=?,repair_date=?,cost=?,materials_used=?,notes=?,equipment_inventory_no=?,problem=?,work_done=?,updated_at=?,sync_base_at=?,dirty=0 WHERE uid=?',vals)
                else: self.db.execute('INSERT INTO repairs(uid,equipment_uid,equipment_name,repair_date,equipment_inventory_no,cost,problem,work_done,materials_used,notes,updated_at,sync_base_at,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)',(uid,'')+vals[:-1])
        self.db.commit()
        return conflicts

    def perform_sync(self):
        started=now()
        try:
            base=self.server_url()
            payload=self.build_sync_payload()
            pushed=self.http_json('POST',base+'/sync',payload,timeout=60)
            if not pushed.get('ok'): raise RuntimeError(pushed.get('error','Windows server xətası'))
            conflicts=pushed.get('conflicts',[])
            conflict_uids={t:set() for t in ('equipment','materials','repairs')}
            for cf in conflicts:
                typ=cf.get('table','')
                if typ in conflict_uids: conflict_uids[typ].add(cf.get('uid',''))
                self.save_conflict(typ,cf.get('uid',''),cf.get('client',{}),cf.get('server',{}))
            for typ in ('equipment','materials','repairs'):
                rows=self.db.execute(f'SELECT uid,updated_at FROM {typ} WHERE dirty=1').fetchall()
                for r in rows:
                    if r['uid'] not in conflict_uids[typ]:
                        self.db.execute(f'UPDATE {typ} SET dirty=0,sync_base_at=? WHERE uid=?',(r['updated_at'],r['uid']))
            self.db.execute('UPDATE files SET dirty=0 WHERE dirty=1')
            last=self.db.execute("SELECT value FROM device_info WHERE key='last_sync'").fetchone()
            since=last['value'] if last else '1970-01-01T00:00:00'
            pulled=self.http_json('GET',base+'/pull?since='+urllib.parse.quote(since),timeout=30)
            if not pulled.get('ok'): raise RuntimeError(pulled.get('error','Windows məlumatları alınmadı'))
            pulled_conflicts=self.apply_server_changes(pulled.get('changes',[]))
            pulled_files=self.http_json('GET',base+'/pull_files?since='+urllib.parse.quote(since),timeout=60)
            if not pulled_files.get('ok'): raise RuntimeError(pulled_files.get('error','Windows faylları alınmadı'))
            for pf in pulled_files.get('files',[]): self.register_pulled_file(pf)
            server_time=pulled.get('server_time') or pushed.get('server_time') or now()
            self.db.execute("INSERT OR REPLACE INTO device_info(key,value) VALUES('last_sync',?)",(server_time,))
            self.db.execute("INSERT INTO sync_log(direction,started_at,finished_at,status,details) VALUES(?,?,?,?,?)",('İKİ TƏRƏFLİ',started,now(),'OK',json.dumps({'göndərildi':pushed.get('counts',{}),'alındı':len(pulled.get('changes',[])), 'fayl':len(pulled_files.get('files',[])), 'toqquşma':len(conflicts)+pulled_conflicts},ensure_ascii=False)))
            self.db.commit(); self.sync_label.text=f"Sinxronizasiya tamamlandı. Alındı: {len(pulled.get('changes',[]))}, fayl: {len(pulled_files.get('files',[]))}. Toqquşma: {len(conflicts)+pulled_conflicts}"
            self.refresh_equipment(); self.refresh_repairs(); self.refresh_materials()
        except Exception as e:
            self.db.execute("INSERT INTO sync_log(direction,started_at,finished_at,status,details) VALUES(?,?,?,?,?)",('İKİ TƏRƏFLİ',started,now(),'ERROR',str(e))); self.db.commit(); self.sync_label.text='Sinxronizasiya xətası: '+str(e)


    def show_conflicts(self):
        rows=self.db.execute("SELECT * FROM sync_conflicts WHERE resolved=0 ORDER BY id DESC").fetchall()
        if not rows:
            self.info('Həll olunmamış toqquşma yoxdur.','Toqquşmalar')
            return
        box=BoxLayout(orientation='vertical',padding=dp(10),spacing=dp(8))
        box.add_widget(Label(text=f'Həll olunmamış toqquşmalar: {len(rows)}',size_hint_y=None,height=dp(40)))
        scroll=ScrollView()
        items=BoxLayout(orientation='vertical',spacing=dp(8),size_hint_y=None)
        items.bind(minimum_height=items.setter('height'))
        for r in rows:
            typ={'equipment':'Avadanlıq','repairs':'Təmir','materials':'Material'} .get(r['table_name'],r['table_name'])
            try: client=json.loads(r['client_json'] or '{}'); server=json.loads(r['server_json'] or '{}')
            except Exception: client={}; server={}
            title=client.get('inventory_no') or client.get('name') or client.get('equipment_name') or r['uid']
            card=BoxLayout(orientation='vertical',size_hint_y=None,height=dp(150),spacing=dp(4))
            card.add_widget(Label(text=f'{typ}: {title}',size_hint_y=None,height=dp(30)))
            card.add_widget(Label(text=f"Planşet: {client.get('updated_at','')}\nWindows: {server.get('updated_at','')}",size_hint_y=None,height=dp(48)))
            rowb=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(5))
            a=Button(text='Planşet versiyası'); a.bind(on_release=lambda _, rid=r['id'], c=client, t=r['table_name']: self.resolve_conflict(rid,t,c,True)); rowb.add_widget(a)
            b=Button(text='Windows versiyası'); b.bind(on_release=lambda _, rid=r['id'], t=r['table_name'], s=server: self.resolve_conflict(rid,t,s,False)); rowb.add_widget(b)
            card.add_widget(rowb); items.add_widget(card)
        scroll.add_widget(items); box.add_widget(scroll)
        close=Button(text='Bağla',size_hint_y=None,height=dp(48)); box.add_widget(close)
        pop=Popup(title='Sinxronizasiya toqquşmaları',content=box,size_hint=(.96,.90)); close.bind(on_release=pop.dismiss); pop.open()

    def resolve_conflict(self,rid,typ,data,from_client):
        try:
            uid=data.get('uid');
            if typ=='equipment':
                vals=(data.get('inventory_no',''),data.get('name',''),data.get('brand_model',data.get('nomenclature','')),data.get('purchase_date',''),data.get('designation',''),data.get('condition','İşlək'),data.get('notes',''),data.get('updated_at',now()),data.get('updated_at',now()),uid)
                exists=self.db.execute('SELECT id FROM equipment WHERE uid=?',(uid,)).fetchone()
                if exists: self.db.execute('UPDATE equipment SET inventory_no=?,name=?,brand_model=?,purchase_date=?,designation=?,condition=?,notes=?,updated_at=?,sync_base_at=?,dirty=? WHERE uid=?',vals[:-1]+(0 if not from_client else 1,uid))
            elif typ=='materials':
                vals=(data.get('name',''),data.get('purchase_date',''),data.get('number',''),data.get('purpose',data.get('condition','')),data.get('weight',''),data.get('notes',''),data.get('balance',0),data.get('quantity',data.get('balance',0)),data.get('updated_at',now()),data.get('updated_at',now()),uid)
                self.db.execute('UPDATE materials SET name=?,purchase_date=?,number=?,purpose=?,weight=?,notes=?,balance=?,quantity=?,updated_at=?,sync_base_at=?,dirty=? WHERE uid=?',vals[:-1]+(0 if not from_client else 1,uid))
            elif typ=='repairs':
                vals=(data.get('equipment_name',data.get('name','')),data.get('repair_date',data.get('time','')),data.get('cost',0),data.get('materials_used',''),data.get('notes',''),data.get('equipment_inventory_no',data.get('equipment_name','')),data.get('problem',''),data.get('work_done',''),data.get('updated_at',now()),data.get('updated_at',now()),uid)
                self.db.execute('UPDATE repairs SET equipment_name=?,repair_date=?,cost=?,materials_used=?,notes=?,equipment_inventory_no=?,problem=?,work_done=?,updated_at=?,sync_base_at=?,dirty=? WHERE uid=?',vals[:-1]+(0 if not from_client else 1,uid))
            self.db.execute('UPDATE sync_conflicts SET resolved=1 WHERE id=?',(rid,)); self.db.commit()
            self.info('Toqquşma həll edildi. Növbəti sinxronizasiyada seçilmiş versiya göndəriləcək.','Uğurlu')
            self.refresh_equipment(); self.refresh_repairs(); self.refresh_materials()
        except Exception as e: self.info(str(e),'Xəta')

    def sync_status(self):
        n=0
        for t in ('equipment','repairs','materials','files'): n+=self.db.execute(f'SELECT COUNT(*) FROM {t} WHERE dirty=1').fetchone()[0]
        c=self.db.execute('SELECT COUNT(*) FROM sync_conflicts WHERE resolved=0').fetchone()[0]
        self.info(f'{n} dəyişiklik sinxronizasiya üçün gözləyir.\nHəll olunmamış toqquşma: {c}','Sinxronizasiya')

if __name__=='__main__': MechanicMobile().run()
