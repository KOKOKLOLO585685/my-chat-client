import os, json, time, requests, urllib3, socketio, flet as ft

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://my-chat-app-s2fw.onrender.com"
SESSION_FILE = "session.json"

def save_session(user_data):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f)

def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def clear_session():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)

def main(page: ft.Page):
    page.title, page.rtl = "تطبيق المراسلة", True
    state = {"user": None, "home": False}
    sio = socketio.Client(ssl_verify=False)

    def msg_box(txt):
        page.open(ft.SnackBar(ft.Text(txt)))

    def avatar_url(path):
        return f"{BASE_URL}{path}?t={int(time.time())}" if path else "https://placeholder.com"

    def start_session(user_data):
        state["user"] = user_data
        save_session(user_data)
        if not sio.connected:
            try:
                sio.connect(BASE_URL, transports=['websocket', 'polling'])
                time.sleep(0.5)
            except Exception:
                pass
        if sio.connected:
            sio.emit("register_user_socket", user_data["id"])
            sio.on("refresh_home", lambda d: (msg_box(d["msg"]), load_home() if state["home"] else None))
        load_home()

    def logout(_):
        clear_session()
        state["user"] = None
        if sio.connected:
            sio.disconnect()
        show_auth()

    # --- 1. شاشة الحسابات ---
    u_in = ft.TextField(label="اسم المستخدم")
    p_in = ft.TextField(label="كلمة المرور", password=True)
    status_lbl = ft.Text("", color="orange", weight="bold")

    def auth(ep):
        if not u_in.value or not p_in.value:
            status_lbl.value = "يرجى إدخال اسم المستخدم وكلمة المرور"
            page.update()
            return
        status_lbl.value = "جاري الاتصال بالسيرفر..."
        page.update()
        try:
            r = requests.post(f"{BASE_URL}/{ep}", json={"username": u_in.value, "password": p_in.value}, timeout=60, verify=False)
            if r.status_code == 200:
                status_lbl.value = ""
                start_session(r.json())
            else:
                try:
                    status_lbl.value = r.json().get("detail", "خطأ في البيانات")
                except Exception:
                    status_lbl.value = f"خطأ من السيرفر ({r.status_code})"
                page.update()
        except Exception as e:
            status_lbl.value = f"تعذر الاتصال: {e}"
            page.update()

    def show_auth():
        state["home"] = False
        page.clean()
        page.add(
            ft.Text("تسجيل الدخول", size=24, weight="bold"),
            u_in, p_in, status_lbl,
            ft.Row([
                ft.Button("دخول", on_click=lambda _: auth("login")),
                ft.OutlinedButton("حساب جديد", on_click=lambda _: auth("register"))
            ])
        )

    # --- 2. الشاشة الرئيسية ---
    async def change_avatar(_):
        files = await ft.FilePicker().pick_files(file_type=ft.FilePickerFileType.IMAGE)
        if files and len(files) > 0:
            with open(files[0].path, "rb") as f:
                requests.post(f"{BASE_URL}/upload-avatar/{state['user']['id']}", files={"file": f}, verify=False)
            load_home()

    def load_home():
        state["home"] = True
        try:
            res = requests.get(f"{BASE_URL}/user-data/{state['user']['id']}", timeout=30, verify=False)
            if res.status_code != 200:
                clear_session()
                show_auth()
                return
            data = res.json()
        except Exception:
            show_auth()
            return
        
        state["user"] = data["user"]
        save_session(data["user"])
        f_in = ft.TextField(hint_text="اسم صديق", expand=True)
        g_in = ft.TextField(hint_text="اسم قروب جديد", expand=True)
        s_in = ft.TextField(hint_text="بحث عن قروب", expand=True)
        s_res = ft.Column()

        def search_grp(_):
            res_g = requests.get(f"{BASE_URL}/search-groups", params={"q": s_in.value}, verify=False).json()
            my_ids = [g["id"] for g in data["groups"]]
            s_res.controls = [ft.Row([ft.Text(g["name"], expand=True),
                ft.Text("منضم") if g["id"] in my_ids else ft.Button("انضمام", on_click=lambda _, gid=g["id"]: (requests.post(f"{BASE_URL}/join-group", json={"group_id": gid, "user_id": state["user"]["id"]}, verify=False), load_home()))
            ]) for g in res_g]
            page.update()

        def get_priv_id(id1, id2):
            ids = sorted([id1, id2])
            return f"priv_{ids[0]}_{ids[1]}"

        page.clean()
        page.add(ft.ListView(expand=True, controls=[
            ft.Row([
                ft.CircleAvatar(foreground_image_src=avatar_url(state["user"]["avatar"])),
                ft.Text(state["user"]["username"], size=18, weight="bold", expand=True),
                ft.IconButton(ft.Icons.CAMERA_ALT, tooltip="تغيير الصورة", on_click=change_avatar),
                ft.IconButton(ft.Icons.LOGOUT, tooltip="تسجيل الخروج", icon_color="red", on_click=logout)
            ]),
            ft.Row([f_in, ft.Button("إضافة", on_click=lambda _: (requests.post(f"{BASE_URL}/friend-request", json={"sender_id": state["user"]["id"], "target_username": f_in.value}, verify=False), msg_box("تم الإرسال")))]),
            *[ft.Row([ft.Text(r["username"]), ft.Button("قبول", on_click=lambda _, rid=r["id"]: requests.post(f"{BASE_URL}/accept-friend", json={"user_id": state["user"]["id"], "requester_id": rid}, verify=False))]) for r in data["requests"]],
            ft.Divider(), ft.Text("الأصدقاء:", weight="bold"),
            *[ft.ListTile(leading=ft.CircleAvatar(foreground_image_src=avatar_url(f["avatar"])), title=ft.Text(f["username"]),
                on_click=lambda _, f=f: open_chat(get_priv_id(state["user"]["id"], f["id"]), f["username"])) for f in data["friends"]],
            ft.Divider(),
            ft.Row([s_in, ft.Button("بحث", on_click=search_grp)]), s_res,
            ft.Row([g_in, ft.Button("إنشاء قروب", on_click=lambda _: requests.post(f"{BASE_URL}/create-group", json={"name": g_in.value, "admin_id": state["user"]["id"], "member_ids": [f["id"] for f in data["friends"]]}, verify=False))]),
            ft.Text("القروبات:", weight="bold"),
            *[ft.ListTile(leading=ft.Icon(ft.Icons.GROUP), title=ft.Text(g["name"]), on_click=lambda _, g=g: open_chat(f"grp_{g['id']}", g["name"])) for g in data["groups"]]
        ]))

    # --- 3. شاشة المحادثة ---
    def open_chat(cid, title):
        state["home"] = False
        chat_lv = ft.ListView(expand=True, spacing=8, auto_scroll=True)
        m_in = ft.TextField(hint_text="رسالتك...", expand=True)

        def add_bubble(m):
            me = m["sender_id"] == state["user"]["id"]
            chat_lv.controls.append(ft.Container(content=ft.Text(f"{m['sender_name']}: {m['text']}", color="white"),
                bgcolor="blue" if me else "grey", padding=10, border_radius=10,
                alignment=ft.Alignment.CENTER_RIGHT if me else ft.Alignment.CENTER_LEFT))

        for m in requests.get(f"{BASE_URL}/messages/{cid}", verify=False).json(): add_bubble(m)
        sio.on("receive_message", lambda d: (add_bubble(d), page.update()) if d["chat_id"] == cid else None)
        sio.emit("join_chat", cid)

        def send(_):
            if m_in.value.strip():
                sio.emit("send_message", {"chat_id": cid, "sender_id": state["user"]["id"], "sender_name": state["user"]["username"], "text": m_in.value})
                m_in.value = ""; page.update()

        page.clean()
        page.add(ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: load_home()), ft.Text(title, size=18, weight="bold")]),
                 chat_lv, ft.Row([m_in, ft.IconButton(ft.Icons.SEND, on_click=send)]))

    saved = load_session()
    if saved:
        start_session(saved)
    else:
        show_auth()

ft.run(main)
