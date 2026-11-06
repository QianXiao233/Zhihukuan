import sys
import os
import json
import warnings
warnings.filterwarnings("ignore")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib import cm

# ── 3D surface 支持 ──
try:
    from mpl_toolkits.mplot3d import Axes3D
    _HAS_3D = True
except ImportError:
    _HAS_3D = False


class NpyViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NPY Viewer")
        self.geometry("1200x750")
        self.arr = None
        self.file_path = ""
        self._slice_idx = 0
        self._dnd_ok = False

        self._build_ui()

        # 支持拖放文件
        self.drop_target_register()
        if self._dnd_ok:
            self.dnd_bind('<<Drop>>', self._on_drop)

    # ─────── UI 构建 ───────

    def _build_ui(self):
        # ── 顶部工具栏 ──
        tbar = ttk.Frame(self)
        tbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4)

        ttk.Button(tbar, text="Open", command=self._open_file).pack(side=tk.LEFT, padx=2)
        ttk.Label(tbar, text="  View:").pack(side=tk.LEFT, padx=2)
        self.view_combo = ttk.Combobox(tbar, values=["2D Heatmap", "3D Surface", "Data Table"],
                                       state="readonly", width=14)
        self.view_combo.current(0)
        self.view_combo.pack(side=tk.LEFT, padx=2)
        self.view_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_view())

        ttk.Separator(tbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(tbar, text="Export Image", command=self._export_image).pack(side=tk.LEFT, padx=2)

        ttk.Label(tbar, text="  Drop an .npy/.npz file here or click Open",
                  foreground="gray").pack(side=tk.RIGHT, padx=8)

        # ── 信息栏 ──
        self.info_label = tk.Label(self, text="No file loaded",
                                   anchor=tk.W, justify=tk.LEFT,
                                   font=("Consolas", 10), bg="#eee",
                                   padx=6, pady=4)
        self.info_label.pack(side=tk.TOP, fill=tk.X, padx=4)

        # ── 视图容器 ──
        self.view_frame = ttk.Frame(self)
        self.view_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # 2D 画布
        self.fig_2d = Figure(figsize=(6, 5), dpi=100)
        self.canvas_2d = FigureCanvasTkAgg(self.fig_2d, master=self.view_frame)
        self.canvas_2d.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Slice 滑块
        sb_frame = ttk.Frame(self)
        sb_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
        self.slice_label = ttk.Label(sb_frame, text="Slice: 0/0")
        self.slice_label.pack(side=tk.LEFT, padx=2)
        self.slice_slider = ttk.Scale(sb_frame, from_=0, to=0, orient=tk.HORIZONTAL,
                                      command=self._on_slice_changed)
        self.slice_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._slice_widget = sb_frame
        self._slice_widget.pack_forget()  # 默认隐藏

    # ─────── 拖放支持 ───────
    def drop_target_register(self):
        try:
            self.tk.eval('package require tkdnd 2.0')
            self.tk.eval('tkdnd::drop_target register . {DND_Files}')
            self._dnd_ok = True
        except tk.TclError:
            self._dnd_ok = False

    def dnd_bind(self, event, callback):
        if self._dnd_ok:
            self._dnd_callback = callback
            self.tk.eval(f'bind . {event} {{+ {self._dnd_cmd} }}')

    def _dnd_cmd(self, *args):
        files = self.tk.splitlist(self.tk.eval('::tkdnd::get_drop_data .'))
        for f in files:
            f = f.strip()
            if f.endswith(('.npy', '.npz')):
                self._load(f)
                break

    def _on_drop(self, event):
        pass  # tkdnd 通过 _dnd_cmd 处理

    # ─────── 文件操作 ───────

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Open NPY/NPZ",
            filetypes=[("NumPy Files", "*.npy *.npz"), ("All Files", "*.*")]
        )
        if path:
            self._load(path)

    def _load(self, path):
        try:
            self.arr = np.load(path, allow_pickle=True)
            self.file_path = path
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        self._update_info()
        self._update_slider()
        self._refresh_view()

    # ─────── 信息更新 ───────

    @staticmethod
    def _safe_stat(arr):
        if arr.size == 0:
            return None, None
        try:
            return arr.min(), arr.max()
        except Exception:
            return None, None

    def _update_info(self):
        arr = self.arr
        lines = [
            f"File: {self.file_path}",
            f"Shape: {arr.shape}   Dtype: {arr.dtype}   "
            f"Size: {arr.size:,}   Ndim: {arr.ndim}"
        ]
        if arr.dtype == object:
            if arr.size > 0:
                elem = arr.flat[0]
                lines.append(f"Object array — element type: {type(elem).__name__}")
        elif arr.size > 0:
            mn, mx = self._safe_stat(arr)
            if mn is not None:
                info = f"Min: {mn}   Max: {mx}"
                if np.issubdtype(arr.dtype, np.floating):
                    try:
                        info += f"   Mean: {arr.mean():.6f}"
                    except Exception:
                        pass
                lines.append(info)
        self.info_label.config(text="\n".join(lines))

    # ─────── Slice 滑块 ───────

    def _update_slider(self):
        ndim = self.arr.ndim
        if ndim <= 2:
            self._slice_widget.pack_forget()
            self._slice_idx = 0
        else:
            self._slice_idx = 0
            total = max(self.arr.shape[0] - 1, 0)
            self.slice_slider.config(from_=0, to=total)
            self.slice_slider.set(0)
            self.slice_label.config(text=f"Slice: 0/{total}")
            self._slice_widget.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))

    def _on_slice_changed(self, val):
        total = max(self.arr.shape[0] - 1, 0)
        idx = int(round(float(val)))
        self.slice_label.config(text=f"Slice: {idx}/{total}")
        self._slice_idx = idx
        self._refresh_view()

    # ─────── 视图分发 ───────

    def _refresh_view(self):
        if self.arr is None:
            return
        view = self.view_combo.get()
        ndim = self.arr.ndim

        if self.arr.dtype == object or ndim == 0:
            self._show_table()
            return

        if view == "Data Table":
            self._show_table()
        elif view == "3D Surface":
            self._show_3d(ndim)
        else:
            self._show_2d(ndim)

    def _switch_canvas(self, canvas_widget):
        for w in self.view_frame.winfo_children():
            w.pack_forget()
        canvas_widget.pack(fill=tk.BOTH, expand=True)

    # ─────── 2D Heatmap ───────

    def _show_2d(self, ndim):
        self.fig_2d.clear()
        data = self._slice_2d(ndim)

        if data.ndim != 2:
            ax = self.fig_2d.add_subplot(111)
            ax.text(0.5, 0.5, "Cannot display as 2D",
                    transform=ax.transAxes, ha='center', va='center')
        else:
            ax = self.fig_2d.add_subplot(111)
            im = ax.imshow(data, aspect='auto', cmap='viridis', origin='upper')
            self.fig_2d.colorbar(im, ax=ax, shrink=0.85)
            title = f"Slice shape: {data.shape}"
            if ndim > 2:
                title = f"Slice [{self._slice_idx}] / {self.arr.shape[0] - 1} of " \
                        f"{self.arr.shape}  —  {title}"
            ax.set_title(title)

        self.canvas_2d.draw()
        self._switch_canvas(self.canvas_2d.get_tk_widget())

    # ─────── 3D Surface ───────

    def _show_3d(self, ndim):
        self.fig_2d.clear()
        data = self._slice_2d(ndim)

        if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 2:
            ax = self.fig_2d.add_subplot(111)
            ax.text(0.5, 0.5, "Need 2D array (>=2x2) for 3D surface",
                    transform=ax.transAxes, ha='center', va='center')
        elif not _HAS_3D:
            ax = self.fig_2d.add_subplot(111)
            ax.text(0.5, 0.5, "mpl_toolkits.mplot3d not available",
                    transform=ax.transAxes, ha='center', va='center')
        else:
            h, w = data.shape
            max_dim = 200
            if h > max_dim or w > max_dim:
                step = max(h // max_dim, w // max_dim, 1)
                data = data[::step, ::step]

            X, Y = np.meshgrid(np.arange(data.shape[1]), np.arange(data.shape[0]))
            ax = self.fig_2d.add_subplot(111, projection='3d')
            ax.plot_surface(X, Y, data, cmap='viridis', linewidth=0, antialiased=True)
            title = f"Slice shape (shown): {data.shape}"
            if ndim > 2:
                title = f"Slice [{self._slice_idx}] / {self.arr.shape[0] - 1} of " \
                        f"{self.arr.shape}  —  {title}"
            ax.set_title(title)

        self.canvas_2d.draw()
        self._switch_canvas(self.canvas_2d.get_tk_widget())

    # ─────── 切片辅助 ───────

    def _slice_2d(self, ndim):
        arr = self.arr
        if ndim == 1:
            return arr.reshape(1, -1)
        elif ndim == 2:
            return arr
        else:
            return arr[self._slice_idx]

    # ─────── 格式化值 ───────

    @staticmethod
    def _fmt(val, max_len=500):
        if isinstance(val, dict):
            if not val:
                return "{}"
            parts = []
            for k, v in val.items():
                if len(parts) >= 5:
                    parts.append(f"... (+{len(val) - 5} more)")
                    break
                parts.append(f"{repr(k)}: {NpyViewer._fmt(v, 60)}")
            return "{" + ", ".join(parts) + "}"
        elif isinstance(val, (list, tuple)):
            if len(val) == 0:
                return "[]" if isinstance(val, list) else "()"
            cls = "[]" if isinstance(val, list) else "()"
            items = []
            for i, v in enumerate(val):
                if len(items) >= 10:
                    items.append(f"... (+{len(val) - 10} more)")
                    break
                items.append(NpyViewer._fmt(v, 40))
            return cls[0] + ", ".join(items) + cls[1]
        elif isinstance(val, np.ndarray):
            if val.size == 0:
                return f"ndarray({val.shape}, {val.dtype})"
            flat = val.flat
            items = []
            for i in range(min(val.size, 10)):
                items.append(str(flat[i]))
            if val.size > 10:
                items.append(f"... (+{val.size - 10})")
            return f"[{', '.join(items)}]"
        elif isinstance(val, (np.floating, float)):
            return f"{val:.6g}"
        elif isinstance(val, bytes):
            s = val.decode("utf-8", errors="replace")
            if len(s) > max_len:
                s = s[:max_len] + "..."
            return s
        else:
            s = str(val)
            if len(s) > max_len:
                s = s[:max_len] + "..."
            return s

    # ─────── 表格视图 ───────

    def _show_table(self):
        for w in self.view_frame.winfo_children():
            w.pack_forget()

        ndim = self.arr.ndim
        if ndim == 0:
            data = np.atleast_2d(self.arr.item())
        elif ndim == 1:
            data = self.arr.reshape(-1, 1)
        elif ndim == 2:
            data = self.arr
        else:
            data = self.arr[self._slice_idx]
            if data.ndim == 1:
                data = data.reshape(-1, 1)

        max_rows = 5000
        if data.shape[0] > max_rows:
            data = data[:max_rows]

        rows, cols = data.shape

        container = ttk.Frame(self.view_frame)
        container.pack(fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(container, orient=tk.HORIZONTAL)

        columns = [f"Col{c}" for c in range(cols)]
        self.table = ttk.Treeview(container, columns=columns, show="headings",
                                  yscrollcommand=vsb.set, xscrollcommand=hsb.set,
                                  height=min(rows, 30))
        vsb.config(command=self.table.yview)
        hsb.config(command=self.table.xview)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for c in range(cols):
            self.table.heading(columns[c], text=str(c))
            self.table.column(columns[c], width=120, minwidth=60, anchor=tk.W)

        for r in range(rows):
            values = []
            for c in range(cols):
                val = data[r, c]
                values.append(self._fmt(val))
            self.table.insert("", tk.END, values=values)

        self.table.bind("<Double-1>", self._cell_detail)
        self._current_table_data = data

    def _cell_detail(self, event):
        item = self.table.selection()
        if not item:
            return
        col = self.table.identify_column(event.x)
        col_idx = int(col.replace("#", "")) - 1
        row_idx = self.table.index(item[0])

        data = getattr(self, '_current_table_data', None)
        if data is None or row_idx >= data.shape[0] or col_idx >= data.shape[1]:
            return
        val = data[row_idx, col_idx]
        full = repr(val)
        if isinstance(val, dict):
            try:
                full = json.dumps(val, indent=2, ensure_ascii=False, default=str)
            except Exception:
                pass
        elif isinstance(val, np.ndarray):
            full = np.array2string(val, threshold=2000, edgeitems=20)

        win = tk.Toplevel(self)
        win.title(f"Detail — row {row_idx}, col {col_idx}")
        win.geometry("700x500")
        txt = tk.Text(win, wrap=tk.NONE, font=("Consolas", 12))
        scroll_y = ttk.Scrollbar(win, orient=tk.VERTICAL, command=txt.yview)
        scroll_x = ttk.Scrollbar(win, orient=tk.HORIZONTAL, command=txt.xview)
        txt.config(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        txt.insert(tk.END, full)
        txt.config(state=tk.DISABLED)

    # ─────── 导出图片 ───────

    def _export_image(self):
        if self.arr is None or self.arr.dtype == object:
            messagebox.showinfo("Info", "Export is only available for numeric data in plot view.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Image",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPG", "*.jpg"), ("All", "*.*")]
        )
        if not path:
            return
        self.fig_2d.savefig(path, dpi=150, bbox_inches='tight')


# ─────── 入口 ───────

def main():
    app = NpyViewer()
    if len(sys.argv) > 1:
        app._load(sys.argv[1])
    app.mainloop()


if __name__ == "__main__":
    main()
