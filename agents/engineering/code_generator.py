"""Shared code generation utility for engineering agents.

Wraps LLM calls with code-specific formatting, validation, and extraction.
Supports Python, TypeScript, Dockerfile, and YAML generation.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from agents.engineering.prompts import CODE_GENERATION_PROMPT, CODE_REVIEW_PROMPT
from evalplatform.llm import create_llm_client

logger = structlog.get_logger()


class Language(str, Enum):
    """Supported code generation languages."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    DOCKERFILE = "dockerfile"
    YAML = "yaml"
    SQL = "sql"
    SHELL = "shell"


@dataclass
class CodeBlock:
    """A generated code block with metadata."""

    language: Language
    code: str
    filename: str | None = None
    description: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True if no validation errors were found."""
        return len(self.errors) == 0


@dataclass
class ReviewResult:
    """Result of a code review."""

    approved: bool
    score: int
    issues: list[dict[str, str]]
    summary: str


class CodeGenerator:
    """Wraps LLM calls for structured code generation.

    Provides language-specific generation methods with built-in
    validation and formatting. Designed to be shared across all
    engineering agents.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.4,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = create_llm_client()

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Make a raw LLM call and return the response content."""
        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
            )
            return response.content
        except Exception:
            logger.exception("code_generator_llm_call_failed", model=self.model)
            raise

    def _extract_code_block(self, text: str, language: str) -> str:
        """Extract a fenced code block from LLM output.

        Handles cases where the LLM returns code in fenced blocks, or
        returns raw code without fences.
        """
        # Try language-specific fence first
        pattern = rf"```{re.escape(language)}\s*\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Try generic fence
        pattern = r"```\s*\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fall back to treating the whole response as code
        return text.strip()

    def _build_generation_prompt(
        self,
        task_description: str,
        requirements: str,
        tech_stack: str,
        language: str,
    ) -> str:
        """Build a prompt from the code generation template."""
        return CODE_GENERATION_PROMPT.format(
            task_description=task_description,
            requirements=requirements,
            tech_stack=tech_stack,
            language=language,
        )

    def _validate_python(self, code: str) -> list[str]:
        """Validate Python code by parsing the AST."""
        errors: list[str] = []
        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(f"Python syntax error at line {e.lineno}: {e.msg}")
        return errors

    def _validate_typescript(self, code: str) -> list[str]:
        """Perform basic structural validation on TypeScript/TSX code.

        This is a lightweight heuristic check -- full validation requires
        the TypeScript compiler which is not available here.
        """
        errors: list[str] = []

        # Check balanced braces
        if code.count("{") != code.count("}"):
            errors.append(
                f"Unbalanced braces: {code.count('{')} opening vs "
                f"{code.count('}')} closing"
            )

        # Check balanced parentheses
        if code.count("(") != code.count(")"):
            errors.append(
                f"Unbalanced parentheses: {code.count('(')} opening vs "
                f"{code.count(')')} closing"
            )

        return errors

    def _validate_dockerfile(self, code: str) -> list[str]:
        """Validate Dockerfile has required structure."""
        errors: list[str] = []
        lines = [line.strip() for line in code.splitlines() if line.strip() and not line.strip().startswith("#")]
        if not lines:
            errors.append("Dockerfile is empty")
            return errors

        if not any(line.upper().startswith("FROM") for line in lines):
            errors.append("Dockerfile must contain at least one FROM instruction")

        return errors

    def _validate_yaml(self, code: str) -> list[str]:
        """Validate YAML syntax using basic structural checks.

        Avoids importing PyYAML so the generator has no heavy dependencies.
        """
        errors: list[str] = []
        if not code.strip():
            errors.append("YAML content is empty")
            return errors

        # Check for tab characters (YAML forbids them for indentation)
        for i, line in enumerate(code.splitlines(), start=1):
            if line.startswith("\t"):
                errors.append(f"Line {i}: YAML does not allow tab indentation")
                break

        return errors

    def _validate(self, code: str, language: Language) -> list[str]:
        """Dispatch validation to the language-specific validator."""
        validators = {
            Language.PYTHON: self._validate_python,
            Language.TYPESCRIPT: self._validate_typescript,
            Language.DOCKERFILE: self._validate_dockerfile,
            Language.YAML: self._validate_yaml,
        }
        validator = validators.get(language)
        if validator is None:
            return []
        return validator(code)

    async def generate(
        self,
        task_description: str,
        language: Language,
        requirements: str = "",
        tech_stack: str = "",
        filename: str | None = None,
        extra_context: str = "",
    ) -> CodeBlock:
        """Generate code for a given task.

        Args:
            task_description: What the code should accomplish.
            language: Target language for generation.
            requirements: Specific requirements or constraints.
            tech_stack: Technology stack context.
            filename: Optional output filename.
            extra_context: Additional context appended to the user message.

        Returns:
            A CodeBlock containing the generated code and validation results.
        """
        prompt = self._build_generation_prompt(
            task_description=task_description,
            requirements=requirements,
            tech_stack=tech_stack,
            language=language.value,
        )
        if extra_context:
            prompt += f"\n\n## Additional Context\n{extra_context}"

        messages = [{"role": "user", "content": prompt}]

        logger.info(
            "code_generation_started",
            language=language.value,
            task=task_description[:80],
        )

        raw_response = await self._call_llm(messages)
        code = self._extract_code_block(raw_response, language.value)
        errors = self._validate(code, language)

        block = CodeBlock(
            language=language,
            code=code,
            filename=filename,
            description=task_description,
            errors=errors,
        )

        logger.info(
            "code_generation_completed",
            language=language.value,
            valid=block.is_valid,
            error_count=len(errors),
        )

        return block

    async def generate_python(
        self,
        task_description: str,
        requirements: str = "",
        filename: str | None = None,
        extra_context: str = "",
    ) -> CodeBlock:
        """Generate Python code (FastAPI, SQLAlchemy, Pydantic, etc.)."""
        return await self.generate(
            task_description=task_description,
            language=Language.PYTHON,
            requirements=requirements,
            tech_stack="Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2, PostgreSQL",
            filename=filename,
            extra_context=extra_context,
        )

    async def generate_typescript(
        self,
        task_description: str,
        requirements: str = "",
        filename: str | None = None,
        extra_context: str = "",
    ) -> CodeBlock:
        """Generate TypeScript/React code (Next.js, TailwindCSS, etc.)."""
        return await self.generate(
            task_description=task_description,
            language=Language.TYPESCRIPT,
            requirements=requirements,
            tech_stack="Next.js 14, TypeScript, TailwindCSS, Shadcn/ui, React Query, Recharts",
            filename=filename,
            extra_context=extra_context,
        )

    async def generate_dockerfile(
        self,
        task_description: str,
        requirements: str = "",
        filename: str | None = None,
        extra_context: str = "",
    ) -> CodeBlock:
        """Generate a Dockerfile."""
        return await self.generate(
            task_description=task_description,
            language=Language.DOCKERFILE,
            requirements=requirements,
            tech_stack="Docker, multi-stage builds, Alpine/Debian slim base images",
            filename=filename or "Dockerfile",
            extra_context=extra_context,
        )

    async def generate_yaml(
        self,
        task_description: str,
        requirements: str = "",
        filename: str | None = None,
        extra_context: str = "",
    ) -> CodeBlock:
        """Generate YAML configuration (docker-compose, GitHub Actions, etc.)."""
        return await self.generate(
            task_description=task_description,
            language=Language.YAML,
            requirements=requirements,
            tech_stack="Docker Compose, GitHub Actions, Kubernetes manifests",
            filename=filename,
            extra_context=extra_context,
        )

    async def review_code(
        self,
        code: str,
        language: Language,
        context: str = "",
    ) -> ReviewResult:
        """Review a code block for quality and correctness.

        Args:
            code: The source code to review.
            language: Language of the code.
            context: Additional context about what the code should do.

        Returns:
            A ReviewResult with approval status, score, and issues.
        """
        prompt = CODE_REVIEW_PROMPT.format(
            language=language.value,
            code=code,
            context=context,
        )
        messages = [{"role": "user", "content": prompt}]

        logger.info("code_review_started", language=language.value)

        raw_response = await self._call_llm(
            messages,
            temperature=0.2,
        )

        result = self._parse_review_response(raw_response)

        logger.info(
            "code_review_completed",
            approved=result.approved,
            score=result.score,
            issue_count=len(result.issues),
        )

        return result

    def _parse_review_response(self, raw: str) -> ReviewResult:
        """Parse the LLM review response into a ReviewResult.

        Handles both clean JSON and JSON embedded in markdown fences.
        """
        import json

        # Try to extract JSON from fenced block
        json_match = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        json_str = json_match.group(1).strip() if json_match else raw.strip()

        try:
            data: dict[str, Any] = json.loads(json_str)
            return ReviewResult(
                approved=bool(data.get("approved", False)),
                score=int(data.get("score", 5)),
                issues=data.get("issues", []),
                summary=str(data.get("summary", "")),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "code_review_parse_failed",
                error=str(exc),
                raw_length=len(raw),
            )
            return ReviewResult(
                approved=False,
                score=0,
                issues=[],
                summary=f"Failed to parse review response: {exc}",
            )
