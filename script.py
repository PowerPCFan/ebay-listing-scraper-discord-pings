import re

print("Regex tester\n")

test_str = str(input("Enter a string to match the pattern against >>> "))
pattern_input = str(input("Enter your regex pattern (ensure that \\ is represented as \\\\) >>> "))

print("Pattern repr: ", pattern_input.__repr__())

mainmatch = re.findall(pattern=pattern_input, string=test_str.lower(), flags=re.IGNORECASE)
print("\n\nMatches:", bool(mainmatch))
print("Object:", mainmatch.__repr__())
