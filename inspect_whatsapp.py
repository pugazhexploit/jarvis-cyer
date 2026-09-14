import uiautomation as auto
import sys

def print_whatsapp_tree():
    # Find WhatsApp window
    wa_window = auto.WindowControl(searchDepth=1, ClassName="WinUIDesktopWin32WindowClass", Name="WhatsApp")
    if not wa_window.Exists(3, 1):
        wa_window = auto.WindowControl(searchDepth=1, Name="WhatsApp")
        if not wa_window.Exists(3, 1):
            print("WhatsApp window not found.")
            return

    print(f"Found Window: {wa_window.Name} ({wa_window.ClassName})")
    
    with open("whatsapp_tree.txt", "w", encoding="utf-8") as f:
        for control, depth in auto.WalkControl(wa_window, maxDepth=10):
            indent = " " * (depth * 2)
            try:
                line = f"{indent}- {control.ControlTypeName}: Name='{control.Name}', AutomationId='{control.AutomationId}', ClassName='{control.ClassName}'\n"
                f.write(line)
            except Exception as e:
                pass
    print("Tree dumped to whatsapp_tree.txt")

if __name__ == '__main__':
    print_whatsapp_tree()
