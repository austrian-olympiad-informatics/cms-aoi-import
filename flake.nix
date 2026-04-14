{
  description = "CMS AOI Import - Python application for importing tasks to CMS";

  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      perSystem =
        {
          config,
          self',
          inputs',
          pkgs,
          lib,
          system,
          ...
        }:
        let
          randomseedPython = lib.makeOverridable (
            {
              python ? pkgs.python3,
            }:
            pkgs.runCommand "randomseed-python" { } ''
              cp -r ${python} $out
              chmod u+w $out/lib/${python.libPrefix}/random.py
              cat >> $out/lib/${python.libPrefix}/random.py <<EOF
              if 'CMS_AOI_SEED' in _os.environ:
                seed(int(_os.environ['CMS_AOI_SEED']))
              EOF
            ''
          ) { };

          latex = pkgs.texlive.combine {
              inherit (pkgs.texlive)
                scheme-basic
                latexmk

                babel-german
                hyphen-german
                ntgclass
                ucs
                zref
                needspace

                a4wide
                amsmath
                babel
                caption
                changepage
                colortbl
                courier
                enumitem
                eurosym
                etoolbox
                fancyhdr
                float
                hyperref
                lastpage
                listings
                mathtools
                mdframed
                multirow
                placeins
                pstricks
                subfig
                titlesec
                todonotes
                units
                wrapfig
                xcolor
                ;
            };

          defaults = { inherit randomseedPython; };

          cmsAOI = lib.makeOverridable (
            {
              python ? pkgs.python3,
              cms ? null,
              randomseedPython ? defaults.randomseedPython,
              texinputs ? "/tasks/latex:/tasks/figures:",
            }:
            let
              realCmsAOI = python.pkgs.buildPythonApplication {
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

                  find . -name '*.py' -exec sed -i 's/"-static",//' {} \;
                  find . -name '*.py' -exec sed -i 's/ -static//' {} \;
                  sed -i 's/==/>=/' requirements.txt

                  sed -i 's#$aoiseed python3#$aoiseed ${randomseedPython}/bin/python3#' cmsaoi/rule.py
                  sed -i '/^    patch_pth()/d' cmsaoi/__main__.py
                '';

                buildInputs = [ pkgs.ninja ];

                propagatedBuildInputs =
                  with python.pkgs;
                  [
                    colorama
                    voluptuous
                    pyyaml
                    tabulate
                  ]
                  ++ lib.optional (cms != null) cms;

                doCheck = false;

                meta = {
                  description = "CMS AOI Import - Python application for importing tasks to CMS";
                  homepage = "https://github.com/austrian-olympiad-informatics/cms-aoi-import";
                  license = lib.licenses.mit;
                };
              };
            in
            pkgs.writeShellApplication {
              name = "cmsAOI";
              runtimeInputs = [
                realCmsAOI
                pkgs.ninja
                pkgs.gcc
                pkgs.pandoc
                latex
              ];

              text = ''
                export TEXINPUTS=${texinputs}
                exec ${realCmsAOI}/bin/cmsAOI "$@"
              '';
            }
          ) { };
        in
        {
          packages = {
            default = cmsAOI;
            randomseed-python = randomseedPython;
            latex = latex;
          };

          apps.default = {
            type = "app";
            program = "${cmsAOI}/bin/cmsAOI";
          };

          checks.randomseed-python =
            let
              cmd = "${randomseedPython}/bin/python3 -c 'import random; print(random.random())'";
            in
            pkgs.runCommand "randomseed-python-check" { } ''
              mkdir $out
              CMS_AOI_SEED=42 ${cmd} | tee $out/out1.txt
              CMS_AOI_SEED=43 ${cmd} | tee $out/out2.txt
              CMS_AOI_SEED=42 ${cmd} | tee $out/out3.txt

              if cmp -s $out/out1.txt $out/out2.txt; then
                echo "Seed 42 and 43 are equal, but they should not be!"
                exit 1
              fi
              if ! cmp -s $out/out1.txt $out/out3.txt; then
                echo "Seed 42 is not equal to itself, but it should be!"
                exit 1
              fi
            '';
        };
    };
}
