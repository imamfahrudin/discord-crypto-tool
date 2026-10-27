class C:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"

def color_signal(signal):
    if signal == "STRONG BUY":
        return f"{C.BOLD}{C.GREEN}{signal}{C.RESET}"
    if signal == "BUY":
        return f"{C.GREEN}{signal}{C.RESET}"
    if signal == "STRONG SELL":
        return f"{C.BOLD}{C.RED}{signal}{C.RESET}"
    if signal == "SELL":
        return f"{C.RED}{signal}{C.RESET}"
    return f"{C.YELLOW}{signal}{C.RESET}"
