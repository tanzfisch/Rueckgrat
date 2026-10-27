from typing import Dict,  Any
import ast
import math
import operator
from .tool import Tool, ToolCategory

from app.common import get_logger, MessageQueue
logger = get_logger()

# safe calculator: the expression is parsed into a syntax tree (ast) and only whitelisted nodes are evaluated.
# never eval(), so "__import__('os').system(...)" is rejected instead of executed.
MAX_EXPRESSION_LENGTH = 200
MAX_EXPONENT = 1000

BINARY_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FUNCTIONS = {
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x), "abs": abs, "round": round,
    "min": min, "max": max, "floor": math.floor, "ceil": math.ceil,
    "exp": math.exp, "ln": math.log, "log": math.log, "log10": math.log10, "log2": math.log2,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "radians": math.radians, "degrees": math.degrees, "factorial": lambda n: math.factorial(int(n)) if 0 <= n <= 100 else math.nan,
}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


class CalculationError(Exception):
    pass


def _evaluate(node):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in CONSTANTS:
        return CONSTANTS[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculationError(f"exponent too large (max {MAX_EXPONENT})")
        return BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
        return UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        return FUNCTIONS[node.func.id](*[_evaluate(arg) for arg in node.args])
    raise CalculationError(f"unsupported element '{ast.unparse(node) if hasattr(ast, 'unparse') else type(node).__name__}'")


def calculate(expression: str) -> str:
    """returns the formatted result, raises CalculationError for user facing problems"""
    expression = str(expression).strip()
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculationError(f"expression empty or longer than {MAX_EXPRESSION_LENGTH} characters")
    # people (and LLMs) write ^ for power, × and ÷ for multiply and divide
    normalized = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError:
        raise CalculationError(f"invalid expression '{expression}'")
    try:
        value = _evaluate(tree)
    except ZeroDivisionError:
        raise CalculationError("division by zero")
    except (ValueError, OverflowError, TypeError) as e:
        raise CalculationError(f"math error: {e}")

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalculationError("result is not a finite number")
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    return f"{value:.12g}" if isinstance(value, float) else str(value)


class CalculatorTool(Tool):
    category = ToolCategory.MATH
    description = "exact arithmetic and math (sums, percentages, tips, powers, roots, trigonometry)"
    question = "Does the user want something calculated?"

    def __init__(self, db, infrastructure, user_id: int, contact_id: int, conversation_id: int, response: Dict[str, Any], tool_call: Dict[str, Any]):
        super().__init__(db, infrastructure, user_id, contact_id, conversation_id, response, tool_call)

    @classmethod
    def name(cls) -> str:
        return "calculate"

    def execute(self) -> None:
        if not "expression" in self.tool_call:
            logger.error("invalid calculate")
            return None

        expression = self.tool_call["expression"]
        MessageQueue().send_status_message("calculating")

        try:
            result = {"tool": self.name(), "text": f"{expression} = {calculate(expression)}"}
        except CalculationError as e:
            logger.warning(f"calculate {expression} failed: {e}")
            result = {"tool": self.name(), "error": str(e)}
        except Exception as e:
            logger.error(f"failed to calculate {repr(e)}")
            result = {"tool": self.name(), "error": "calculation failed"}

        self.response.setdefault("tool_results", []).append(result)

    @classmethod
    def prompt(cls) -> str:
        return """
CALCULATE:
Use for any arithmetic or math (sums, percentages, tips, powers, roots, trigonometry).
Operators: + - * / // % ** ( )
Functions: sqrt, abs, round, min, max, floor, ceil, exp, ln, log10, log2, sin, cos, tan (radians), factorial
Constants: pi, e

Parameters:
- expression (string, required): the math expression to evaluate

Example:
{"tool": "calculate", "expression": "0.15 * 84.50"}
"""
