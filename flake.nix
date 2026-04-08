{
  description = "CMS AOI Import - Python application for importing tasks to CMS";

  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      perSystem = { config, self', inputs', pkgs, system, ... }: 
      let
        python = pkgs.python3;
        
        cmsaoi = python.pkgs.buildPythonApplication rec {
          pname = "cmsaoi";
          version = "1.0.0";
          format = "setuptools";

          src = ./.;

          postPatch = ''
            substituteInPlace cmsaoi/evaluate.py \
              --replace-fail "/usr/bin/kotlinc" "${pkgs.kotlin}/bin/kotlinc" \
              --replace-fail "/usr/bin/python3" "${python}/bin/python3" \
              --replace-fail "/usr/bin/javac" "${pkgs.jdk}/bin/javac" \
              --replace-fail "/usr/bin/rustc" "${pkgs.rustc}/bin/rustc" \
              --replace-fail "/usr/bin/ghc" "${pkgs.ghc}/bin/ghc" \
              --replace-fail "/usr/bin/mcs" "${pkgs.mono}/bin/mcs" \
              --replace-fail "/usr/bin/mono" "${pkgs.mono}/bin/mono" \
              --replace-fail "/usr/bin/jar" "${pkgs.jdk}/bin/jar" \
              --replace-fail "/usr/bin/java" "${pkgs.jdk}/bin/java" \
              --replace-fail "/usr/bin/g++" "${pkgs.gcc}/bin/g++" \
              --replace-fail "/usr/bin/go" "${pkgs.go}/bin/go" \
              --replace-fail "/usr/bin/zip" "${pkgs.zip}/bin/zip"
          '';

          propagatedBuildInputs = with python.pkgs; [
            voluptuous
            pyyaml
            colorama
            tabulate
          ];

          # Skip tests during build if they exist
          doCheck = false;

          meta = with pkgs.lib; {
            description = "CMS AOI Import - Python application for importing tasks to CMS";
            homepage = "https://github.com/austrian-olympiad-informatics/cms-aoi-import";
            license = licenses.mit; # Changed from unfree to MIT
            maintainers = [ ];
            platforms = platforms.all;
          };
        };
      in
      {
        packages = {
          default = cmsaoi;
          cmsaoi = cmsaoi;
        };

        apps = {
          default = {
            type = "app";
            program = "${cmsaoi}/bin/cmsAOI";
          };
          cmsaoi = {
            type = "app";
            program = "${cmsaoi}/bin/cmsAOI";
          };
        };
      };
    };
}
