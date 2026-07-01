from abc import ABC, abstractmethod

class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict

    @abstractmethod
    def run(self, **kwargs) -> str:
        pass