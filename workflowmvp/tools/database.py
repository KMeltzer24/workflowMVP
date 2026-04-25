"""Database-shaped tools: SQLite query/insert helpers."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from ._base import Tool


class DatabaseToolsMixin:
    def _register_database_tools(self) -> None:
        self.register_tool(Tool(
            name="sqlite_query",
            description="Execute SQL query on SQLite database",
            function=self._sqlite_query,
            parameters={
                "database_path": "Path to SQLite database file",
                "query": "SQL query to execute",
                "params": "Optional query parameters (list or dict)",
            },
        ))
        self.register_tool(Tool(
            name="sqlite_insert",
            description="Insert data into SQLite database",
            function=self._sqlite_insert,
            parameters={
                "database_path": "Path to SQLite database file",
                "table": "Table name",
                "data": "Data to insert (dict or list of dicts)",
            },
        ))

    def _sqlite_query(
        self,
        database_path: str,
        query: str,
        params: Optional[List] = None,
    ) -> Dict[str, Any]:
        try:
            safe_db = self._sandbox_path(database_path)
            conn = sqlite3.connect(safe_db)
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            if query.strip().upper().startswith("SELECT"):
                results = cursor.fetchall()
                columns = (
                    [d[0] for d in cursor.description]
                    if cursor.description
                    else []
                )
                conn.close()
                return {"success": True, "results": results, "columns": columns}
            conn.commit()
            conn.close()
            return {"success": True, "message": "Query executed successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _sqlite_insert(
        self,
        database_path: str,
        table: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            safe_db = self._sandbox_path(database_path)
            conn = sqlite3.connect(safe_db)
            cursor = conn.cursor()

            if isinstance(data, list):
                columns = list(data[0].keys())
                placeholders = ", ".join(["?" for _ in columns])
                query = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                values = [tuple(record[col] for col in columns) for record in data]
                cursor.executemany(query, values)
            else:
                columns = list(data.keys())
                values = list(data.values())
                placeholders = ", ".join(["?" for _ in columns])
                query = (
                    f"INSERT INTO {table} ({', '.join(columns)}) "
                    f"VALUES ({placeholders})"
                )
                cursor.execute(query, values)

            conn.commit()
            conn.close()
            return {"success": True, "message": f"Inserted data into {table}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
