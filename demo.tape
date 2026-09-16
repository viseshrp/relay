Set Shell bash
Set FontSize 18
Set Width 1000
Set Height 700
Set TypingSpeed 30ms
Output demo.gif

Hide
Type "clear"
Enter
Type "DEMO_ROOT=$(mktemp -d)"
Enter
Type "mkdir $DEMO_ROOT/repo && cd $DEMO_ROOT/repo"
Enter
Type "export XDG_DATA_HOME=$DEMO_ROOT/data XDG_CONFIG_HOME=$DEMO_ROOT/config"
Enter
Type "git init -q -b main && git config user.name Relay-Demo && git config user.email relay-demo@example.invalid"
Enter
Type "clear"
Enter

Show
Type "relay --help"
Enter
Sleep 4s

Hide
Type "clear"
Enter
Show
Type "relay init"
Enter
Sleep 2s
Type "find .relay -type f | sort"
Enter
Sleep 3s

Hide
Type "git add .relay && git commit -q -m Add-Relay-workflow"
Enter
Show
Type "relay up --no-browser --port 17850"
Enter
Sleep 5s
Ctrl+C
Sleep 3s
