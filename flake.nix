{
  description = "casio — configure Casio G-Shock watches over BLE from Linux";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, uv2nix, pyproject-nix, pyproject-build-systems }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
      overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

      python = pkgs.python312;

      pythonSet =
        (pkgs.callPackage pyproject-nix.build.packages { inherit python; })
        .overrideScope (pkgs.lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          overlay
        ]);

      venv = pythonSet.mkVirtualEnv "casio-env" workspace.deps.default;
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [ venv pkgs.uv pkgs.basedpyright pkgs.ruff ];
        env = {
          UV_NO_SYNC             = "1";
          UV_PYTHON              = "${venv}/bin/python";
          UV_PYTHON_DOWNLOADS    = "never";
          UV_PROJECT_ENVIRONMENT = "${venv}";
        };
        shellHook = ''unset PYTHONPATH'';
      };
    };
}
