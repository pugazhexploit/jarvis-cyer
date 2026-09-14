import uiautomation as auto

def print_tree():
    try:
        root = auto.GetRootControl()
        for child in root.GetChildren():
            print(f"Top-level: Name='{child.Name}', ClassName='{child.ClassName}'")
            if child.Name == "WhatsApp":
                print(">>> Found WhatsApp!")
                with open('wa_tree.txt', 'w', encoding='utf-8') as f:
                    for c, depth in auto.WalkControl(child, maxDepth=10):
                        f.write(f"{'  ' * depth}- {c.ControlTypeName} '{c.Name}' ({c.ClassName})\n")
    except Exception as e:
        print("Error:", e)

if __name__ == '__main__':
    print_tree()
