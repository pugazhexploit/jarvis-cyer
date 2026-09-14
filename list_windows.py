import uiautomation as auto

def list_windows():
    for win in auto.GetRootControl().GetChildren():
        if win.ControlType == auto.ControlType.WindowControl:
            print(f"'{win.Name}' - Class: '{win.ClassName}'")

if __name__ == '__main__':
    list_windows()
