import uiautomation as auto
import os
import psutil

def main():
    docs_dir = os.path.join(os.path.dirname(__file__), 'docs')
    os.makedirs(docs_dir, exist_ok=True)
    
    info_file = os.path.join(docs_dir, 'whatsapp_actual_window_info.txt')
    tree_file = os.path.join(docs_dir, 'whatsapp_actual_uia_tree.txt')
    
    # 1. Find WhatsApp Process and Window dynamically
    print("Searching for WhatsApp Desktop window...")
    wa_window = None
    
    # Try finding by looking at all top-level windows
    for win in auto.GetRootControl().GetChildren():
        try:
            name = win.Name
            cls_name = win.ClassName
            pid = win.ProcessId
            try:
                proc_name = psutil.Process(pid).name()
            except:
                proc_name = "Unknown"
                
            if "WhatsApp" in proc_name or "WhatsApp" in name:
                wa_window = win
                with open(info_file, "w", encoding="utf-8") as f:
                    f.write(f"WhatsApp Process Name: {proc_name}\n")
                    f.write(f"PID: {pid}\n")
                    f.write(f"Window Title: {name}\n")
                    f.write(f"Class Name: {cls_name}\n")
                    f.write(f"Framework: {win.FrameworkId}\n")
                    f.write(f"UIA Availability: YES\n")
                print(f"Found WhatsApp Desktop! PID: {pid}, Title: '{name}'")
                break
        except Exception as e:
            continue
            
    if not wa_window:
        print("ERROR: WhatsApp Desktop window not found.")
        print("Ensure WhatsApp is OPEN and VISIBLE before running this script.")
        with open(info_file, "w", encoding="utf-8") as f:
            f.write("ERROR: WhatsApp Desktop window not found in current session.\n")
        return

    # Bring to front for accurate bounding rects
    try:
        wa_window.SetActive()
    except:
        pass

    print("Dumping UI tree. This might take a moment...")
    
    with open(tree_file, "w", encoding="utf-8") as f:
        f.write(f"--- WHATSAPP UI TREE FOR '{wa_window.Name}' ---\n")
        
        for control, depth in auto.WalkControl(wa_window, maxDepth=12):
            indent = " " * (depth * 2)
            try:
                c_type = control.ControlTypeName
                c_name = control.Name
                c_auto_id = control.AutomationId
                c_class = control.ClassName
                c_framework = control.FrameworkId
                c_enabled = control.IsEnabled
                c_offscreen = control.IsOffscreen
                c_rect = control.BoundingRectangle
                
                line = (f"{indent}- {c_type}: Name='{c_name}', AutomationId='{c_auto_id}', "
                        f"ClassName='{c_class}', FrameworkId='{c_framework}', "
                        f"IsEnabled={c_enabled}, IsOffscreen={c_offscreen}, Rect={c_rect}\n")
                f.write(line)
            except Exception as e:
                f.write(f"{indent}- ERROR reading control: {e}\n")
                
    print(f"Diagnostics complete!\nWindow Info saved to: {info_file}\nUI Tree saved to: {tree_file}")

if __name__ == '__main__':
    main()
