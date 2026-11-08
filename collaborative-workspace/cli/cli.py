import sys
from backend.workspace.manager import WorkspaceManager

manager = WorkspaceManager()

def print_help():
    print("""
Usage:

# Workspace
python cli/cli.py workspace create
python cli/cli.py workspace list
python cli/cli.py workspace delete <workspace_id>

# File
python cli/cli.py file create <workspace_id> <filename>
python cli/cli.py file write <workspace_id> <filename>
python cli/cli.py file read <workspace_id> <filename>
python cli/cli.py file delete <workspace_id> <filename>
python cli/cli.py file list <workspace_id>

# Run
python cli/cli.py run <workspace_id> <filename>
""")

# ---------------- CLI START ----------------

args = sys.argv

if len(args) < 3:
    print_help()
    exit()

module = args[1]
command = args[2]

# ---------------- WORKSPACE ----------------

if module == "workspace":

    if command == "create":
        wid = manager.create_workspace()
        print(f"Workspace created: {wid}")

    elif command == "list":
        workspaces = manager.list_workspaces()
        if not workspaces:
            print("No workspaces found")
        else:
            for w in workspaces:
                print(w)

    elif command == "delete":
        if len(args) < 4:
            print("Workspace ID required")
        else:
            manager.delete_workspace(args[3])
            print("Workspace deleted")

# ---------------- FILE ----------------

elif module == "file":

    if command == "list":
        if len(args) < 4:
            print("Missing workspace ID")
            exit()
        wid = args[3]
    else:
        if len(args) < 5:
            print("Missing arguments")
            exit()
        wid = args[3]
        filename = args[4]

    if command == "create":
        manager.create_file(wid, filename)
        print("File created")

    elif command == "write":
        print("Enter code (type END to finish):")
        lines = []
        while True:
            line = input()
            if line == "END":
                break
            lines.append(line)

        manager.write_file(wid, filename, "\n".join(lines))
        print("File saved")

    elif command == "read":
        content = manager.read_file(wid, filename)
        print("\n----- FILE CONTENT -----\n")
        print(content)

    elif command == "delete":
        manager.delete_file(wid, filename)
        print("File deleted")

    elif command == "list":
        files = manager.list_files(wid)
        for f in files:
            print(f)

# ---------------- RUN ----------------

elif module == "run":

    if len(args) < 4:
        print("Missing arguments")
        exit()

    wid = args[2]
    filename = args[3]

    try:
        result = manager.run_file(wid, filename)
        print(result["stdout"], end="")
        print(result["stderr"], end="")
        if result["exit_code"] != 0:
            print("Exit code:", result["exit_code"])
    except Exception as e:
        print("Error:", str(e))

else:
    print("Unknown command")
    print_help()